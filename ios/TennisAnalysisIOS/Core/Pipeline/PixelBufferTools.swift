import AVFoundation
import CoreGraphics
import CoreImage
import CoreML
import Foundation

enum PixelBufferTools {
    private static let ciContext = CIContext(options: nil)

    static func pixelBuffer(from sampleBuffer: CMSampleBuffer) throws -> CVPixelBuffer {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            throw AnalysisErrors.unsupportedVideo
        }
        return pixelBuffer
    }

    static func resizedPixelBuffer(
        from pixelBuffer: CVPixelBuffer,
        width: Int,
        height: Int
    ) throws -> CVPixelBuffer {
        var output: CVPixelBuffer?
        let attributes: [CFString: Any] = [
            kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey: width,
            kCVPixelBufferHeightKey: height,
            kCVPixelBufferIOSurfacePropertiesKey: [:],
        ]
        let status = CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA, attributes as CFDictionary, &output)
        guard status == kCVReturnSuccess, let output else {
            throw AnalysisErrors.unsupportedVideo
        }

        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let scaleX = CGFloat(width) / image.extent.width
        let scaleY = CGFloat(height) / image.extent.height
        let resized = image.transformed(by: CGAffineTransform(scaleX: scaleX, y: scaleY))
        ciContext.render(resized, to: output)
        return output
    }

    static func copyPixelBuffer(
        from pixelBuffer: CVPixelBuffer,
        using pool: CVPixelBufferPool? = nil
    ) throws -> CVPixelBuffer {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let output: CVPixelBuffer
        if let pool {
            var pooled: CVPixelBuffer?
            CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &pooled)
            guard let pooled else {
                throw AnalysisErrors.exportFailed
            }
            output = pooled
        } else {
            output = try resizedPixelBuffer(from: pixelBuffer, width: width, height: height)
            return output
        }

        let image = CIImage(cvPixelBuffer: pixelBuffer)
        ciContext.render(image, to: output)
        return output
    }

    static func makeCGImage(from pixelBuffer: CVPixelBuffer) -> CGImage? {
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        return ciContext.createCGImage(
            image,
            from: CGRect(
                x: 0,
                y: 0,
                width: CVPixelBufferGetWidth(pixelBuffer),
                height: CVPixelBufferGetHeight(pixelBuffer)
            )
        )
    }

    static func normalizedMultiArray(
        from pixelBuffer: CVPixelBuffer,
        width: Int,
        height: Int,
        mean: [Float],
        std: [Float]
    ) throws -> MLMultiArray {
        let resized = try resizedPixelBuffer(from: pixelBuffer, width: width, height: height)
        let array = try MLMultiArray(shape: [1, 3, NSNumber(value: height), NSNumber(value: width)], dataType: .float32)

        CVPixelBufferLockBaseAddress(resized, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(resized, .readOnly) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(resized) else {
            throw AnalysisErrors.unsupportedVideo
        }
        let bytesPerRow = CVPixelBufferGetBytesPerRow(resized)
        let buffer = baseAddress.assumingMemoryBound(to: UInt8.self)

        let meanValues = mean.count == 3 ? mean : [0, 0, 0]
        let stdValues = std.count == 3 ? std : [1, 1, 1]

        for y in 0..<height {
            for x in 0..<width {
                let pixelOffset = y * bytesPerRow + x * 4
                let b = Float(buffer[pixelOffset]) / 255.0
                let g = Float(buffer[pixelOffset + 1]) / 255.0
                let r = Float(buffer[pixelOffset + 2]) / 255.0
                let values = [
                    (r - meanValues[0]) / stdValues[0],
                    (g - meanValues[1]) / stdValues[1],
                    (b - meanValues[2]) / stdValues[2],
                ]
                for channel in 0..<3 {
                    let index = channel * width * height + y * width + x
                    array[index] = NSNumber(value: values[channel])
                }
            }
        }

        return array
    }
}
