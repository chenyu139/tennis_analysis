import Foundation

@MainActor
final class HomeViewModel: ObservableObject {
    @Published var selectedVideoURL: URL?
    @Published var isProcessing = false
    @Published var progress = 0.0
    @Published var statusText = "Waiting for a local video."

    private let processor = OfflineVideoProcessor()

    func handleVideoImport(result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            selectedVideoURL = urls.first
            statusText = urls.first.map { "Ready to process \($0.lastPathComponent)." } ?? "No video selected."
        case .failure(let error):
            statusText = "Video import failed: \(error.localizedDescription)"
        }
    }

    func startProcessing() {
        guard let selectedVideoURL else {
            statusText = "Please select a local video first."
            return
        }
        isProcessing = true
        progress = 0.0
        statusText = "Preparing offline analysis..."

        Task {
            do {
                let outputURL = try await processor.processVideo(
                    inputURL: selectedVideoURL,
                    progressHandler: { [weak self] progressUpdate, message in
                        Task { @MainActor in
                            self?.progress = progressUpdate
                            self?.statusText = message
                        }
                    }
                )
                isProcessing = false
                progress = 1.0
                statusText = "Exported to \(outputURL.lastPathComponent)."
            } catch {
                isProcessing = false
                statusText = "Processing failed: \(error.localizedDescription)"
            }
        }
    }
}
