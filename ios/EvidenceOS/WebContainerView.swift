import SwiftUI
import WebKit

struct WebContainerView: UIViewRepresentable {
    @Binding var importedText: String

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.scrollView.bounces = true
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.load(URLRequest(url: AppConfig.tryURL))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard !importedText.isEmpty else { return }
        let escaped = importedText
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "`", with: "\\`")
            .replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: "\r", with: "")
        let js = """
        (function(){
          var ta = document.getElementById('text');
          if (!ta) return;
          delete ta.dataset.sample;
          ta.value = `\(escaped)`;
          ta.dispatchEvent(new Event('input'));
        })();
        """
        webView.evaluateJavaScript(js, completionHandler: nil)
        DispatchQueue.main.async { importedText = "" }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        let parent: WebContainerView
        init(parent: WebContainerView) { self.parent = parent }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            let html = """
            <html><body style='font-family:-apple-system;background:#0a0b0f;color:#fff;padding:24px'>
            <h2>EvidenceOS is offline</h2>
            <p>Could not reach the service. Check your connection and try again.</p>
            <p><a href='\(AppConfig.tryURL.absoluteString)'>Retry</a></p>
            </body></html>
            """
            webView.loadHTMLString(html, baseURL: nil)
        }
    }
}
