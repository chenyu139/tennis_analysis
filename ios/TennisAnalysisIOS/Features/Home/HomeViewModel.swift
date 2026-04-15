import Foundation

@MainActor
final class HomeViewModel: ObservableObject {
    @Published var selectedVideoURL: URL?
    @Published var outputVideoURL: URL?
    @Published var exportedVideoURLs: [URL] = []
    @Published var isProcessing = false
    @Published var progress = 0.0
    @Published var statusText = "请选择一个本地视频。"
    @Published var recentEvents: [String] = ["等待导入本地视频"]

    private let processor = OfflineVideoProcessor()
    private var hasAttemptedAutoProcessing = false
    private var lastProgressMessage: String?

    init() {
        refreshExportedVideos()
    }

    func handleVideoImport(result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let importedURL = urls.first else {
                statusText = "未选择任何视频。"
                appendStatusEvent("未选择视频")
                return
            }
            statusText = "正在导入视频..."
            appendStatusEvent("开始导入：\(importedURL.lastPathComponent)")
            Task {
                await importSelectedVideo(from: importedURL)
            }
        case .failure(let error):
            statusText = "视频导入失败：\(error.localizedDescription)"
            appendStatusEvent("视频导入失败：\(error.localizedDescription)")
        }
    }

    func startProcessing() {
        guard let selectedVideoURL else {
            statusText = "请先选择本地视频。"
            appendStatusEvent("开始分析前未选择视频")
            appendDebugLog("startProcessing aborted: no selected video")
            return
        }
        guard FileManager.default.fileExists(atPath: selectedVideoURL.path) else {
            statusText = "选中的视频不存在，请重新导入。"
            appendStatusEvent("视频文件不存在：\(selectedVideoURL.lastPathComponent)")
            return
        }
        isProcessing = true
        progress = 0.0
        outputVideoURL = nil
        lastProgressMessage = nil
        statusText = "正在准备离线分析..."
        appendStatusEvent("开始分析：\(selectedVideoURL.lastPathComponent)")
        appendDebugLog("startProcessing began for \(selectedVideoURL.lastPathComponent)")

        Task {
            do {
                let outputURL = try await processor.processVideo(
                    inputURL: selectedVideoURL,
                    progressHandler: { [weak self] progressUpdate, message in
                        Task { @MainActor in
                            self?.progress = progressUpdate
                            self?.statusText = message
                            if self?.lastProgressMessage != message {
                                self?.lastProgressMessage = message
                                self?.appendStatusEvent(message)
                            }
                            self?.appendDebugLog("progress \(String(format: "%.3f", progressUpdate)): \(message)")
                        }
                    }
                )
                isProcessing = false
                progress = 1.0
                outputVideoURL = outputURL
                refreshExportedVideos()
                statusText = "处理完成，已导出到 \(outputURL.lastPathComponent)。"
                appendStatusEvent("处理完成：\(outputURL.lastPathComponent)")
                appendDebugLog("processing succeeded: \(outputURL.path)")
            } catch {
                isProcessing = false
                statusText = "处理失败：\(error.localizedDescription)"
                appendStatusEvent("处理失败：\(error.localizedDescription)")
                appendDebugLog("processing failed: \(error.localizedDescription)")
            }
        }
    }

    func prepareAutoProcessingIfRequested() {
        refreshExportedVideos()
        guard !hasAttemptedAutoProcessing else { return }
        hasAttemptedAutoProcessing = true

        let environment = ProcessInfo.processInfo.environment
        guard environment["AUTO_PROCESS_DEBUG_VIDEO"] == "1" else { return }
        appendDebugLog("auto processing requested")

        let inputFileName = environment["AUTO_PROCESS_INPUT_FILENAME"] ?? "input_video.mp4"
        guard let documentsDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            statusText = "自动导入失败：找不到 Documents 目录。"
            appendStatusEvent("自动导入失败：找不到 Documents 目录")
            appendDebugLog("auto processing failed: missing Documents directory")
            return
        }

        let autoInputURL = documentsDirectory.appendingPathComponent(inputFileName)
        guard FileManager.default.fileExists(atPath: autoInputURL.path) else {
            statusText = "自动导入失败：Documents 中找不到 \(inputFileName)。"
            appendStatusEvent("自动导入失败：未找到 \(inputFileName)")
            appendDebugLog("auto processing failed: missing file \(autoInputURL.path)")
            return
        }

        selectedVideoURL = autoInputURL
        statusText = "已准备好：\(autoInputURL.lastPathComponent)。"
        appendStatusEvent("自动导入成功：\(autoInputURL.lastPathComponent)")
        appendDebugLog("auto processing found file \(autoInputURL.path)")
        startProcessing()
    }

    func refreshExportedVideos() {
        guard let documentsDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            exportedVideoURLs = []
            return
        }

        let exportsDirectory = documentsDirectory.appendingPathComponent("Exports", isDirectory: true)
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: exportsDirectory,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: [.skipsHiddenFiles]
        )) ?? []

        exportedVideoURLs = urls
            .filter { $0.pathExtension.lowercased() == "mp4" }
            .sorted { lhs, rhs in
                let lhsDate = (try? lhs.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let rhsDate = (try? rhs.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return lhsDate > rhsDate
            }

        if outputVideoURL == nil {
            outputVideoURL = exportedVideoURLs.first
        }
    }

    private func importSelectedVideo(from importedURL: URL) async {
        do {
            let localURL = try copyImportedVideoToDocuments(from: importedURL)
            selectedVideoURL = localURL
            outputVideoURL = nil
            statusText = "已导入：\(localURL.lastPathComponent)。"
            appendStatusEvent("导入完成，可开始分析")
        } catch {
            statusText = "导入失败：\(error.localizedDescription)"
            appendStatusEvent("导入失败：\(error.localizedDescription)")
        }
    }

    private func copyImportedVideoToDocuments(from sourceURL: URL) throws -> URL {
        let accessedSecurityScope = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if accessedSecurityScope {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }

        guard let documentsDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            throw AnalysisErrors.unsupportedVideo
        }

        let importsDirectory = documentsDirectory.appendingPathComponent("ImportedVideos", isDirectory: true)
        try FileManager.default.createDirectory(at: importsDirectory, withIntermediateDirectories: true)

        let sanitizedName = sourceURL.lastPathComponent.isEmpty ? "input.mp4" : sourceURL.lastPathComponent
        let destinationURL = importsDirectory.appendingPathComponent(sanitizedName)

        if sourceURL.standardizedFileURL == destinationURL.standardizedFileURL {
            return destinationURL
        }

        if FileManager.default.fileExists(atPath: destinationURL.path) {
            try FileManager.default.removeItem(at: destinationURL)
        }
        try FileManager.default.copyItem(at: sourceURL, to: destinationURL)
        return destinationURL
    }

    private func appendStatusEvent(_ message: String) {
        recentEvents.insert(message, at: 0)
        if recentEvents.count > 8 {
            recentEvents = Array(recentEvents.prefix(8))
        }
    }

    private func appendDebugLog(_ message: String) {
        let environment = ProcessInfo.processInfo.environment
        guard environment["AUTO_PROCESS_DEBUG_VIDEO"] == "1" else { return }
        guard let documentsDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else { return }

        let logURL = documentsDirectory.appendingPathComponent("auto_process_debug.log")
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let line = "[\(timestamp)] \(message)\n"
        let data = Data(line.utf8)

        if FileManager.default.fileExists(atPath: logURL.path),
           let handle = try? FileHandle(forWritingTo: logURL) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: logURL, options: .atomic)
        }
    }
}
