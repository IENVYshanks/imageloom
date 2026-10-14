// ImageLoom: native macOS shell.
// A window around the system WebKit (no bundled Chromium), the embedded Python server, and nothing else.
// Launch -> starts the server; quit / close window -> stops the server and any running generation.
import Cocoa
import WebKit
import UserNotifications

let appName = "ImageLoom"

// MARK: - language
// The shell speaks Russian when the first preferred system language is Russian, English otherwise. The web UI picks its own
// language from the same setting (navigator.language) and has its own switch, so the two normally agree.
let isRussian = (Locale.preferredLanguages.first ?? "").lowercased().hasPrefix("ru")
func tr(_ en: String, _ ru: String) -> String { isRussian ? ru : en }

// MARK: - helpers

func firstFreePort(preferred: Int) -> Int {
    func canBind(_ port: Int) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        if fd < 0 { return false }
        defer { close(fd) }
        var yes: Int32 = 0
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(UInt16(port).bigEndian)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let rc = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        return rc == 0
    }
    if canBind(preferred) { return preferred }
    for p in (preferred + 1)...(preferred + 60) where canBind(p) { return p }
    return preferred
}

func logsDirectory() -> URL {
    let dir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/\(appName)")
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    return dir
}

func httpGetJSON(_ url: URL, timeout: TimeInterval = 1.5) -> [String: Any]? {
    var result: [String: Any]?
    let sem = DispatchSemaphore(value: 0)
    var req = URLRequest(url: url, timeoutInterval: timeout)
    req.setValue("1", forHTTPHeaderField: "X-ImageLoom")
    URLSession.shared.dataTask(with: req) { data, _, _ in
        if let data = data { result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] }
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + timeout + 0.5)
    return result
}

// MARK: - server lifecycle

final class ServerManager {
    private(set) var process: Process?
    private(set) var port = 7870
    let logURL = logsDirectory().appendingPathComponent("server.log")

    var baseURL: URL { URL(string: "http://127.0.0.1:\(port)")! }

    func start() throws {
        guard let res = Bundle.main.resourceURL else { throw NSError(domain: appName, code: 1, userInfo: [NSLocalizedDescriptionKey: "No resources"]) }
        let python = res.appendingPathComponent("python/bin/python3")
        let core = res.appendingPathComponent("core")
        port = firstFreePort(preferred: 7870)  // a stable port keeps the page's saved settings (localStorage is per origin)

        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let log = try FileHandle(forWritingTo: logURL)

        let p = Process()
        p.executableURL = python
        p.arguments = ["-u", core.appendingPathComponent("server.py").path]
        p.currentDirectoryURL = core
        var env = ProcessInfo.processInfo.environment
        env["IMAGELOOM_PORT"] = String(port)
        env["IMAGELOOM_HOST"] = "mac-app"
        env["IMAGELOOM_ENGINE_DIR"] = res.appendingPathComponent("engine").path
        env["IMAGELOOM_PARENT_PID"] = String(ProcessInfo.processInfo.processIdentifier)  // the server exits by itself if this app dies
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
        p.environment = env
        p.standardOutput = log
        p.standardError = log
        try p.run()
        process = p
    }

    var isRunning: Bool { process?.isRunning ?? false }

    func waitUntilReady(timeout: TimeInterval = 30) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if !isRunning { return false }
            if httpGetJSON(baseURL.appendingPathComponent("api/status"), timeout: 1) != nil { return true }
            Thread.sleep(forTimeInterval: 0.25)
        }
        return false
    }

    /// Ask nicely (SIGTERM: the server cancels the GPU job and removes its port file), then insist.
    func stop() {
        guard let p = process, p.isRunning else { return }
        p.terminate()
        let deadline = Date().addingTimeInterval(4)
        while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }
}

// MARK: - app delegate

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    let server = ServerManager()
    var window: NSWindow!
    var webView: WKWebView!
    var notifyAuthorized = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        showSplash(tr("Starting \(appName)…", "Запуск \(appName)…"))
        DispatchQueue.global().async {
            do {
                try self.server.start()
                if self.server.waitUntilReady() {
                    DispatchQueue.main.async { self.webView.load(URLRequest(url: self.server.baseURL)) }
                } else {
                    DispatchQueue.main.async { self.showFailure() }
                }
            } catch {
                DispatchQueue.main.async { self.showFailure(extra: error.localizedDescription) }
            }
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if server.isRunning, let st = httpGetJSON(server.baseURL.appendingPathComponent("api/status")) {
            let running = st["running"] is String
            let queued = (st["queued"] as? Int) ?? 0
            if running || queued > 0 {
                let alert = NSAlert()
                alert.messageText = tr("Generation in progress", "Идёт генерация")
                alert.informativeText = tr("If you quit now, the current job and the queue (\(queued)) will be cancelled.", "Если выйти сейчас, текущая задача и очередь (\(queued)) будут отменены.")
                alert.addButton(withTitle: tr("Cancel", "Отмена"))
                alert.addButton(withTitle: tr("Quit and Cancel", "Выйти и отменить"))
                alert.alertStyle = .warning
                if alert.runModal() == .alertFirstButtonReturn { return .terminateCancel }
            }
        }
        server.stop()
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) { server.stop() }

    // MARK: window

    func buildWindow() {
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "ig")
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        if #available(macOS 13.3, *) { webView.isInspectable = true }

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1360, height: 880),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = appName
        window.contentMinSize = NSSize(width: 860, height: 600)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = webView
        window.setFrameAutosaveName("ImageLoomMain")
        if !window.setFrameUsingName("ImageLoomMain") { window.center() }
        window.makeKeyAndOrderFront(nil)
    }

    func showSplash(_ text: String) {
        let html = """
        <html lang="\(isRussian ? "ru" : "en")"><body style="margin:0;height:100vh;display:grid;place-items:center;background:#111110;color:#ecece7;font:15px -apple-system,system-ui">
        <div style="text-align:center"><div style="width:34px;height:34px;border:3px solid #333;border-top-color:#7a89ff;border-radius:50%;margin:0 auto 16px;animation:s 1s linear infinite"></div>\(text)</div>
        <style>@keyframes s{to{transform:rotate(360deg)}}</style></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    func showFailure(extra: String = "") {
        let tail = (try? String(contentsOf: server.logURL, encoding: .utf8))?.split(separator: "\n").suffix(12).joined(separator: "\n") ?? ""
        let esc = { (s: String) in s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;") }
        let html = """
        <html lang="\(isRussian ? "ru" : "en")"><body style="margin:40px;background:#111110;color:#ecece7;font:15px -apple-system,system-ui">
        <h2>\(tr("Couldn't start the server", "Не удалось запустить сервер"))</h2><p>\(esc(extra))</p>
        <pre style="background:#1b1b19;padding:14px;border-radius:10px;white-space:pre-wrap;color:#c9c9c2">\(esc(tail))</pre>
        <p>\(tr("Log: Help → “Show Server Log”. Try restarting the app.", "Журнал: Справка → «Показать журнал сервера». Попробуйте перезапустить приложение."))</p></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: menus

    func buildMenu() {
        let main = NSMenu()
        func item(_ title: String, _ action: Selector?, _ key: String = "", mods: NSEvent.ModifierFlags = [.command]) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        // app
        let appItem = NSMenuItem(); main.addItem(appItem)
        let app = NSMenu(); appItem.submenu = app
        app.addItem(item(tr("About \(appName)", "О программе \(appName)"), #selector(NSApplication.orderFrontStandardAboutPanel(_:))))
        app.addItem(.separator())
        app.addItem(item(tr("Hide \(appName)", "Скрыть \(appName)"), #selector(NSApplication.hide(_:)), "h"))
        app.addItem(item(tr("Hide Others", "Скрыть остальные"), #selector(NSApplication.hideOtherApplications(_:)), "h", mods: [.command, .option]))
        app.addItem(item(tr("Show All", "Показать все"), #selector(NSApplication.unhideAllApplications(_:))))
        app.addItem(.separator())
        app.addItem(item(tr("Quit \(appName)", "Завершить \(appName)"), #selector(NSApplication.terminate(_:)), "q"))
        // edit
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: tr("Edit", "Правка")); editItem.submenu = edit
        edit.addItem(item(tr("Undo", "Отменить"), Selector(("undo:")), "z"))
        edit.addItem(item(tr("Redo", "Повторить"), Selector(("redo:")), "Z", mods: [.command, .shift]))
        edit.addItem(.separator())
        edit.addItem(item(tr("Cut", "Вырезать"), #selector(NSText.cut(_:)), "x"))
        edit.addItem(item(tr("Copy", "Копировать"), #selector(NSText.copy(_:)), "c"))
        edit.addItem(item(tr("Paste", "Вставить"), #selector(NSText.paste(_:)), "v"))
        edit.addItem(item(tr("Select All", "Выбрать всё"), #selector(NSText.selectAll(_:)), "a"))
        // view
        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: tr("View", "Вид")); viewItem.submenu = view
        let reload = item(tr("Reload", "Обновить"), #selector(reloadPage), "r"); reload.target = self; view.addItem(reload)
        view.addItem(.separator())
        let zin = item(tr("Zoom In", "Увеличить масштаб"), #selector(zoomIn), "+"); zin.target = self; view.addItem(zin)
        let zout = item(tr("Zoom Out", "Уменьшить масштаб"), #selector(zoomOut), "-"); zout.target = self; view.addItem(zout)
        let zreset = item(tr("Actual Size", "Реальный размер"), #selector(zoomReset), "0"); zreset.target = self; view.addItem(zreset)
        view.addItem(.separator())
        view.addItem(item(tr("Enter Full Screen", "Во весь экран"), #selector(NSWindow.toggleFullScreen(_:)), "f", mods: [.command, .control]))
        // window
        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: tr("Window", "Окно")); winItem.submenu = win
        win.addItem(item(tr("Minimize", "Свернуть"), #selector(NSWindow.performMiniaturize(_:)), "m"))
        win.addItem(item(tr("Zoom", "Масштабировать"), #selector(NSWindow.performZoom(_:))))
        NSApp.windowsMenu = win
        // help
        let helpItem = NSMenuItem(); main.addItem(helpItem)
        let help = NSMenu(title: tr("Help", "Справка")); helpItem.submenu = help
        let pics = item(tr("Open Pictures Folder", "Открыть папку с картинками"), #selector(openPictures)); pics.target = self; help.addItem(pics)
        let data = item(tr("Open Data Folder (models, history)", "Открыть папку данных (модели, история)"), #selector(openDataDir)); data.target = self; help.addItem(data)
        let logItem = item(tr("Show Server Log", "Показать журнал сервера"), #selector(openLog)); logItem.target = self; help.addItem(logItem)
        NSApp.helpMenu = help
        NSApp.mainMenu = main
    }

    @objc func reloadPage() { if webView.url?.host == "127.0.0.1" { webView.reload() } else { webView.load(URLRequest(url: server.baseURL)) } }
    @objc func zoomIn() { webView.pageZoom = min(webView.pageZoom + 0.1, 3) }
    @objc func zoomOut() { webView.pageZoom = max(webView.pageZoom - 0.1, 0.5) }
    @objc func zoomReset() { webView.pageZoom = 1 }
    @objc func openLog() { NSWorkspace.shared.open(server.logURL) }
    @objc func openPictures() {
        if let st = httpGetJSON(server.baseURL.appendingPathComponent("api/status")), let dir = st["output_dir"] as? String {
            NSWorkspace.shared.open(URL(fileURLWithPath: dir))
        }
    }
    @objc func openDataDir() {
        if let st = httpGetJSON(server.baseURL.appendingPathComponent("api/status")), let dir = st["data_dir"] as? String {
            NSWorkspace.shared.open(URL(fileURLWithPath: dir))
        }
    }

    // MARK: JS bridge (notifications when a job finishes while the window is in the background)

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        if type == "notify" {
            let center = UNUserNotificationCenter.current()
            let post = {
                let c = UNMutableNotificationContent()
                c.title = (body["title"] as? String) ?? appName
                c.body = (body["body"] as? String) ?? ""
                c.sound = .default
                center.add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
            }
            if notifyAuthorized { post() } else {
                center.requestAuthorization(options: [.alert, .sound]) { ok, _ in self.notifyAuthorized = ok; if ok { post() } }
            }
        }
    }

    // MARK: navigation: only our own page loads in the window; links go to the default browser; files are downloaded with a save panel

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { decisionHandler(.download); return }
        if let url = action.request.url, let scheme = url.scheme, ["http", "https"].contains(scheme), url.host != "127.0.0.1", url.host != "localhost" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { result in
            if result == .OK, let url = panel.url {
                try? FileManager.default.removeItem(at: url)  // the user confirmed the overwrite in the panel
                completionHandler(url)
            } else { completionHandler(nil) }
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.runModal(); completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message; a.addButton(withTitle: "OK"); a.addButton(withTitle: tr("Cancel", "Отмена"))
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
