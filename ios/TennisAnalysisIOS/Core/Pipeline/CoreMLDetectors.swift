import AVFoundation
import CoreGraphics
import CoreML
import Foundation

struct DetectorConfig {
    let modelBaseName: String
    let confidenceThreshold: Float
    let iouThreshold: Float
    let trackedClassIds: Set<Int>
}

class BaseCoreMLModel {
    let model: MLModel
    let metadata: ModelMetadata
    let inputName: String
    let outputName: String
    let inputImageWidth: Int
    let inputImageHeight: Int

    init(modelBaseName: String) throws {
        self.metadata = try ModelAssetLocator.metadata(baseName: modelBaseName)
        let modelURL = try ModelAssetLocator.modelURL(baseName: modelBaseName)
        self.model = try MLModel(contentsOf: modelURL)
        self.inputName = model.modelDescription.inputDescriptionsByName.keys.first ?? "image"
        self.outputName = model.modelDescription.outputDescriptionsByName.keys.first ?? "output"

        if let imageConstraint = model.modelDescription.inputDescriptionsByName[inputName]?.imageConstraint {
            self.inputImageWidth = imageConstraint.pixelsWide
            self.inputImageHeight = imageConstraint.pixelsHigh
        } else {
            let inputShape = metadata.inputShape ?? []
            let layout = metadata.inputLayout?.uppercased()
            if layout == "NHWC", inputShape.count >= 4 {
                self.inputImageHeight = inputShape[inputShape.count - 3]
                self.inputImageWidth = inputShape[inputShape.count - 2]
            } else if inputShape.count >= 2 {
                self.inputImageHeight = inputShape[inputShape.count - 2]
                self.inputImageWidth = inputShape[inputShape.count - 1]
            } else {
                self.inputImageWidth = 640
                self.inputImageHeight = 640
            }
        }
    }
}

final class YoloCoreMLDetector: BaseCoreMLModel {
    private let config: DetectorConfig

    init(config: DetectorConfig) throws {
        self.config = config
        try super.init(modelBaseName: config.modelBaseName)
    }

    func detect(sampleBuffer: CMSampleBuffer, timestampNs: UInt64) async throws -> [Detection] {
        try autoreleasepool {
            let sourcePixelBuffer = try PixelBufferTools.pixelBuffer(from: sampleBuffer)
            let modelPixelBuffer = try PixelBufferTools.resizedPixelBuffer(
                from: sourcePixelBuffer,
                width: inputImageWidth,
                height: inputImageHeight
            )
            let provider = try MLDictionaryFeatureProvider(dictionary: [inputName: modelPixelBuffer])
            let output = try model.prediction(from: provider)
            guard let multiArray = output.featureValue(for: outputName)?.multiArrayValue else {
                return []
            }
            return decodeYoloLikeOutput(
                multiArray: multiArray,
                outputShape: multiArray.shape.map(\.intValue),
                sourceWidth: CVPixelBufferGetWidth(sourcePixelBuffer),
                sourceHeight: CVPixelBufferGetHeight(sourcePixelBuffer),
                timestampNs: timestampNs
            )
        }
    }

    private func decodeYoloLikeOutput(
        multiArray: MLMultiArray,
        outputShape: [Int],
        sourceWidth: Int,
        sourceHeight: Int,
        timestampNs: UInt64
    ) -> [Detection] {
        let shape: [Int]
        switch outputShape.count {
        case 2:
            shape = [1, outputShape[0], outputShape[1]]
        case 3:
            shape = outputShape
        default:
            return []
        }
        let transposed = shape[1] < shape[2]
        let attributeCount = transposed ? shape[1] : shape[2]
        let candidateCount = transposed ? shape[2] : shape[1]
        guard attributeCount >= 5 else { return [] }

        func value(candidateIndex: Int, attributeIndex: Int) -> Float {
            if transposed {
                return multiArray.floatValue(atFlatIndex: attributeIndex * candidateCount + candidateIndex)
            }
            return multiArray.floatValue(atFlatIndex: candidateIndex * attributeCount + attributeIndex)
        }

        let hasObjectness = attributeCount == 6 || attributeCount == 85
        let classStartIndex = hasObjectness ? 5 : 4
        let classCount = attributeCount - classStartIndex
        var maxCoordinate: Float = 0
        for candidateIndex in 0..<min(candidateCount, 64) {
            maxCoordinate = max(maxCoordinate, value(candidateIndex: candidateIndex, attributeIndex: 0))
            maxCoordinate = max(maxCoordinate, value(candidateIndex: candidateIndex, attributeIndex: 1))
            maxCoordinate = max(maxCoordinate, value(candidateIndex: candidateIndex, attributeIndex: 2))
            maxCoordinate = max(maxCoordinate, value(candidateIndex: candidateIndex, attributeIndex: 3))
        }
        let normalizedCoordinates = maxCoordinate <= 2
        let inputWidth = inputImageWidth
        let inputHeight = inputImageHeight

        var detections: [Detection] = []
        for candidateIndex in 0..<candidateCount {
            let cx = value(candidateIndex: candidateIndex, attributeIndex: 0)
            let cy = value(candidateIndex: candidateIndex, attributeIndex: 1)
            let w = value(candidateIndex: candidateIndex, attributeIndex: 2)
            let h = value(candidateIndex: candidateIndex, attributeIndex: 3)

            var bestClassID = 0
            var bestClassScore = classCount <= 0 ? value(candidateIndex: candidateIndex, attributeIndex: 4) : 0
            if classCount > 0 {
                for classIndex in 0..<classCount {
                    let score = value(candidateIndex: candidateIndex, attributeIndex: classStartIndex + classIndex)
                    if score > bestClassScore {
                        bestClassScore = score
                        bestClassID = classIndex
                    }
                }
            }

            let confidence = hasObjectness && classCount > 0
                ? value(candidateIndex: candidateIndex, attributeIndex: 4) * bestClassScore
                : bestClassScore
            guard confidence >= config.confidenceThreshold else { continue }
            if !config.trackedClassIds.isEmpty && !config.trackedClassIds.contains(bestClassID) {
                continue
            }

            let scaleX = normalizedCoordinates ? Float(sourceWidth) : Float(sourceWidth) / Float(inputWidth)
            let scaleY = normalizedCoordinates ? Float(sourceHeight) : Float(sourceHeight) / Float(inputHeight)
            let left = max(0, min(Float(sourceWidth), (cx - w / 2) * scaleX))
            let top = max(0, min(Float(sourceHeight), (cy - h / 2) * scaleY))
            let right = max(0, min(Float(sourceWidth), (cx + w / 2) * scaleX))
            let bottom = max(0, min(Float(sourceHeight), (cy + h / 2) * scaleY))
            guard (right - left) > 2, (bottom - top) > 2 else { continue }

            detections.append(
                Detection(
                    classId: bestClassID,
                    score: confidence,
                    bbox: BoundingBox(x1: CGFloat(left), y1: CGFloat(top), x2: CGFloat(right), y2: CGFloat(bottom)),
                    timestampNs: timestampNs
                )
            )
        }
        return nonMaximumSuppression(detections: detections, iouThreshold: CGFloat(config.iouThreshold))
    }

    private func nonMaximumSuppression(detections: [Detection], iouThreshold: CGFloat) -> [Detection] {
        var sorted = detections.sorted { $0.score > $1.score }
        var selected: [Detection] = []
        while !sorted.isEmpty {
            let current = sorted.removeFirst()
            selected.append(current)
            sorted.removeAll { candidate in
                candidate.classId == current.classId && Geometry.iou(candidate.bbox, current.bbox) >= iouThreshold
            }
        }
        return selected
    }
}

final class PlayerCoreMLDetector: PlayerDetecting {
    private let detector: YoloCoreMLDetector

    init(modelBaseName: String = "player_detector") throws {
        detector = try YoloCoreMLDetector(
            config: DetectorConfig(
                modelBaseName: modelBaseName,
                confidenceThreshold: 0.3,
                iouThreshold: 0.45,
                trackedClassIds: [0]
            )
        )
    }

    func detectPlayers(sampleBuffer: CMSampleBuffer) async throws -> [Int: BoundingBox] {
        let detections = try await detectDetections(sampleBuffer: sampleBuffer)
        var boxes: [Int: BoundingBox] = [:]
        for (index, detection) in detections.enumerated() {
            boxes[index + 1] = detection.bbox
        }
        return boxes
    }

    func detectDetections(sampleBuffer: CMSampleBuffer) async throws -> [Detection] {
        try await detector.detect(sampleBuffer: sampleBuffer, timestampNs: sampleBuffer.timestampNs)
    }
}

final class BallCoreMLDetector: BallDetecting {
    private let detector: YoloCoreMLDetector

    init(modelBaseName: String = "ball_detector") throws {
        detector = try YoloCoreMLDetector(
            config: DetectorConfig(
                modelBaseName: modelBaseName,
                confidenceThreshold: 0.2,
                iouThreshold: 0.2,
                trackedClassIds: [0]
            )
        )
    }

    func detectBall(sampleBuffer: CMSampleBuffer) async throws -> BoundingBox? {
        let detections = try await detectDetections(sampleBuffer: sampleBuffer)
        return detections.max(by: { $0.score < $1.score })?.bbox
    }

    func detectDetections(sampleBuffer: CMSampleBuffer) async throws -> [Detection] {
        try await detector.detect(sampleBuffer: sampleBuffer, timestampNs: sampleBuffer.timestampNs)
    }
}

final class CourtCoreMLDetector: CourtKeypointDetecting {
    private let model: MLModel
    private let metadata: ModelMetadata
    private let inputName: String
    private let outputName: String

    init(modelBaseName: String = "court_keypoints") throws {
        self.metadata = try ModelAssetLocator.metadata(baseName: modelBaseName)
        let modelURL = try ModelAssetLocator.modelURL(baseName: modelBaseName)
        self.model = try MLModel(contentsOf: modelURL)
        self.inputName = model.modelDescription.inputDescriptionsByName.keys.first ?? "input"
        self.outputName = model.modelDescription.outputDescriptionsByName.keys.first ?? "keypoints"
    }

    func detectCourtKeypoints(sampleBuffer: CMSampleBuffer) async throws -> [CGPoint] {
        try autoreleasepool {
            let pixelBuffer = try PixelBufferTools.pixelBuffer(from: sampleBuffer)
            let inputShape = metadata.inputShape ?? [1, 3, 224, 224]
            let width = inputShape[inputShape.count - 1]
            let height = inputShape[inputShape.count - 2]
            let multiArray = try PixelBufferTools.normalizedMultiArray(
                from: pixelBuffer,
                width: width,
                height: height,
                mean: metadata.normalizeMean ?? [0.485, 0.456, 0.406],
                std: metadata.normalizeStd ?? [0.229, 0.224, 0.225]
            )
            let provider = try MLDictionaryFeatureProvider(dictionary: [inputName: multiArray])
            let output = try model.prediction(from: provider)
            guard let resultArray = output.featureValue(for: outputName)?.multiArrayValue else {
                return []
            }
            let values = alignCourtOutput(outputArray: resultArray.toFloatArray(), outputShape: resultArray.shape.map(\.intValue))
            guard values.count >= 28 else { return [] }

            let sourceWidth = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
            let sourceHeight = CGFloat(CVPixelBufferGetHeight(pixelBuffer))
            return stride(from: 0, to: 28, by: 2).map { index in
                CGPoint(
                    x: CGFloat(values[index]) * sourceWidth / CGFloat(width),
                    y: CGFloat(values[index + 1]) * sourceHeight / CGFloat(height)
                )
            }
        }
    }

    private func alignCourtOutput(outputArray: [Float], outputShape: [Int]) -> [Float] {
        let metadataShape = metadata.outputShape ?? []
        if outputShape == [1, 14, 2] || metadataShape == [1, 14, 2] {
            return (0..<28).map { index in
                let pointIndex = index / 2
                let axis = index % 2
                return outputArray[pointIndex * 2 + axis]
            }
        }
        if outputShape == [1, 2, 14] || metadataShape == [1, 2, 14] {
            return (0..<28).map { index in
                let pointIndex = index / 2
                let axis = index % 2
                return outputArray[axis * 14 + pointIndex]
            }
        }
        return outputArray
    }
}

extension CMSampleBuffer {
    var timestampNs: UInt64 {
        let seconds = CMSampleBufferGetPresentationTimeStamp(self).seconds
        return UInt64(max(0, seconds) * 1_000_000_000.0)
    }
}

private extension MLMultiArray {
    func floatValue(atFlatIndex index: Int) -> Float {
        switch dataType {
        case .float32:
            let pointer = dataPointer.bindMemory(to: Float.self, capacity: count)
            return pointer[index]
        case .double:
            let pointer = dataPointer.bindMemory(to: Double.self, capacity: count)
            return Float(pointer[index])
        case .float16:
            return self[index].floatValue
        default:
            return self[index].floatValue
        }
    }

    func toFloatArray() -> [Float] {
        let count = self.count
        switch dataType {
        case .float32:
            let pointer = dataPointer.bindMemory(to: Float.self, capacity: count)
            return Array(UnsafeBufferPointer(start: pointer, count: count))
        case .double:
            let pointer = dataPointer.bindMemory(to: Double.self, capacity: count)
            return Array(UnsafeBufferPointer(start: pointer, count: count)).map(Float.init)
        case .float16:
            return (0..<count).map { self[$0].floatValue }
        default:
            return (0..<count).map { self[$0].floatValue }
        }
    }
}
