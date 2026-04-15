import AVFoundation
import CoreImage
import Foundation

struct VideoAssetIO {
    func makeAsset(for url: URL) -> AVAsset {
        AVURLAsset(url: url)
    }

    func nominalFrameRate(for asset: AVAsset) async -> Float {
        guard let track = try? await asset.loadTracks(withMediaType: .video).first else {
            return 24
        }
        let frameRate = (try? await track.load(.nominalFrameRate)) ?? 0
        return frameRate > 0 ? frameRate : 24
    }

    func frameSize(for asset: AVAsset) async throws -> CGSize {
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw AnalysisErrors.unsupportedVideo
        }
        let size = try await track.load(.naturalSize)
        let transform = try await track.load(.preferredTransform)
        return CGRect(origin: .zero, size: size).applying(transform).integral.absoluteSize
    }

    func makeFrameReader(for asset: AVAsset) async throws -> (AVAssetReader, AVAssetReaderTrackOutput, AVAssetTrack) {
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw AnalysisErrors.unsupportedVideo
        }
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(
            track: track,
            outputSettings: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            ]
        )
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else {
            throw AnalysisErrors.unsupportedVideo
        }
        reader.add(output)
        return (reader, output, track)
    }

    func makeWriter(
        outputURL: URL,
        frameSize: CGSize,
        frameRate: Float
    ) throws -> (AVAssetWriter, AVAssetWriterInput, AVAssetWriterInputPixelBufferAdaptor) {
        let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
        let input = AVAssetWriterInput(
            mediaType: .video,
            outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: Int(frameSize.width),
                AVVideoHeightKey: Int(frameSize.height),
                AVVideoCompressionPropertiesKey: [
                    AVVideoAverageBitRateKey: 10_000_000,
                    AVVideoExpectedSourceFrameRateKey: Int(max(frameRate, 24)),
                    AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
                ],
            ]
        )
        input.expectsMediaDataInRealTime = false
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: Int(frameSize.width),
                kCVPixelBufferHeightKey as String: Int(frameSize.height),
            ]
        )
        guard writer.canAdd(input) else {
            throw AnalysisErrors.exportFailed
        }
        writer.add(input)
        return (writer, input, adaptor)
    }

    func makeOutputURL(for inputURL: URL) -> URL {
        let fileManager = FileManager.default
        let outputDirectory: URL
        if let documentsDirectory = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first {
            let exportsDirectory = documentsDirectory.appendingPathComponent("Exports", isDirectory: true)
            try? fileManager.createDirectory(at: exportsDirectory, withIntermediateDirectories: true)
            outputDirectory = exportsDirectory
        } else {
            outputDirectory = fileManager.temporaryDirectory
        }
        let baseName = inputURL.deletingPathExtension().lastPathComponent
        return outputDirectory.appendingPathComponent("\(baseName)_analyzed.mp4")
    }
}

private extension CGRect {
    var absoluteSize: CGSize {
        CGSize(width: abs(width), height: abs(height))
    }
}
