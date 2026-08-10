import Foundation
import UniformTypeIdentifiers

enum DocumentImporter {
    static func handle(result: Result<[URL], Error>, onText: @escaping (String) -> Void) {
        switch result {
        case .failure:
            return
        case .success(let urls):
            guard let url = urls.first else { return }
            guard url.startAccessingSecurityScopedResource() else { return }
            defer { url.stopAccessingSecurityScopedResource() }
            if url.pathExtension.lowercased() == "pdf" {
                onText("(PDF imported — paste extracted text in the web demo for now, or use a .txt file)")
                return
            }
            if let data = try? Data(contentsOf: url), let text = String(data: data, encoding: .utf8) {
                onText(String(text.prefix(60_000)))
            }
        }
    }
}
