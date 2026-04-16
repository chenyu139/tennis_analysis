import AVFoundation
import SwiftUI
import UIKit

struct LiveCameraPreviewView: UIViewRepresentable {
    @ObservedObject var analyzer: LiveCameraAnalyzer

    func makeUIView(context: Context) -> CameraPreviewContainerView {
        let view = CameraPreviewContainerView()
        view.previewLayer.session = analyzer.captureSession
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: CameraPreviewContainerView, context: Context) {
        uiView.previewLayer.session = analyzer.captureSession
        uiView.apply(snapshot: analyzer.latestOverlay)
        if let orientation = uiView.currentVideoOrientation {
            analyzer.updateVideoOrientation(orientation)
            if let connection = uiView.previewLayer.connection, connection.isVideoOrientationSupported {
                connection.videoOrientation = orientation
            }
        }
    }
}

final class CameraPreviewContainerView: UIView {
    override class var layerClass: AnyClass {
        AVCaptureVideoPreviewLayer.self
    }

    var previewLayer: AVCaptureVideoPreviewLayer {
        guard let layer = self.layer as? AVCaptureVideoPreviewLayer else {
            fatalError("Expected AVCaptureVideoPreviewLayer backing layer.")
        }
        return layer
    }

    var currentVideoOrientation: AVCaptureVideoOrientation? {
        guard let interfaceOrientation = window?.windowScene?.interfaceOrientation else {
            return .portrait
        }
        return AVCaptureVideoOrientation(interfaceOrientation: interfaceOrientation)
    }

    private let overlayLayer = CALayer()
    private let playersLayer = CAShapeLayer()
    private let ballLayer = CAShapeLayer()
    private let courtLayer = CAShapeLayer()
    private var snapshot: LiveOverlaySnapshot?

    override init(frame: CGRect) {
        super.init(frame: frame)
        isOpaque = true
        clipsToBounds = true

        overlayLayer.masksToBounds = true
        layer.addSublayer(overlayLayer)

        playersLayer.strokeColor = UIColor.systemRed.cgColor
        playersLayer.fillColor = UIColor.clear.cgColor
        playersLayer.lineWidth = 3

        ballLayer.strokeColor = UIColor.systemYellow.cgColor
        ballLayer.fillColor = UIColor.clear.cgColor
        ballLayer.lineWidth = 3

        courtLayer.strokeColor = UIColor.clear.cgColor
        courtLayer.fillColor = UIColor.systemGreen.cgColor

        overlayLayer.addSublayer(playersLayer)
        overlayLayer.addSublayer(ballLayer)
        overlayLayer.addSublayer(courtLayer)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        previewLayer.frame = bounds
        overlayLayer.frame = bounds
        playersLayer.frame = overlayLayer.bounds
        ballLayer.frame = overlayLayer.bounds
        courtLayer.frame = overlayLayer.bounds

        if let orientation = currentVideoOrientation,
           let connection = previewLayer.connection,
           connection.isVideoOrientationSupported {
            connection.videoOrientation = orientation
        }

        renderOverlay()
    }

    func apply(snapshot: LiveOverlaySnapshot?) {
        self.snapshot = snapshot
        renderOverlay()
    }

    private func renderOverlay() {
        guard let snapshot, bounds.width > 0, bounds.height > 0 else {
            playersLayer.path = nil
            ballLayer.path = nil
            courtLayer.path = nil
            return
        }

        let playersPath = UIBezierPath()
        for player in snapshot.players {
            playersPath.append(UIBezierPath(rect: convert(rect: player.cgRect, sourceSize: snapshot.sourceSize)))
        }
        playersLayer.path = playersPath.cgPath

        if let ball = snapshot.ball {
            ballLayer.path = UIBezierPath(rect: convert(rect: ball.cgRect, sourceSize: snapshot.sourceSize)).cgPath
        } else {
            ballLayer.path = nil
        }

        if snapshot.courtPoints.isEmpty {
            courtLayer.path = nil
        } else {
            let courtPath = UIBezierPath()
            for point in snapshot.courtPoints {
                let convertedPoint = convert(point: point, sourceSize: snapshot.sourceSize)
                courtPath.append(UIBezierPath(ovalIn: CGRect(x: convertedPoint.x - 4, y: convertedPoint.y - 4, width: 8, height: 8)))
            }
            courtLayer.path = courtPath.cgPath
        }
    }

    private func convert(rect: CGRect, sourceSize: CGSize) -> CGRect {
        let topLeft = convert(point: CGPoint(x: rect.minX, y: rect.minY), sourceSize: sourceSize)
        let bottomRight = convert(point: CGPoint(x: rect.maxX, y: rect.maxY), sourceSize: sourceSize)
        return CGRect(
            x: topLeft.x,
            y: topLeft.y,
            width: bottomRight.x - topLeft.x,
            height: bottomRight.y - topLeft.y
        )
    }

    private func convert(point: CGPoint, sourceSize: CGSize) -> CGPoint {
        let displayRect = aspectFillRect(contentSize: sourceSize, in: bounds)
        let scaleX = displayRect.width / max(sourceSize.width, 1)
        let scaleY = displayRect.height / max(sourceSize.height, 1)
        return CGPoint(
            x: displayRect.minX + point.x * scaleX,
            y: displayRect.minY + point.y * scaleY
        )
    }

    private func aspectFillRect(contentSize: CGSize, in bounds: CGRect) -> CGRect {
        guard contentSize.width > 0, contentSize.height > 0, bounds.width > 0, bounds.height > 0 else {
            return bounds
        }

        let scale = max(bounds.width / contentSize.width, bounds.height / contentSize.height)
        let width = contentSize.width * scale
        let height = contentSize.height * scale
        return CGRect(
            x: (bounds.width - width) / 2,
            y: (bounds.height - height) / 2,
            width: width,
            height: height
        )
    }
}

private extension TrackedObject {
    var cgRect: CGRect {
        CGRect(
            x: bbox.x1,
            y: bbox.y1,
            width: bbox.x2 - bbox.x1,
            height: bbox.y2 - bbox.y1
        )
    }
}

private extension AVCaptureVideoOrientation {
    init?(interfaceOrientation: UIInterfaceOrientation) {
        switch interfaceOrientation {
        case .portrait:
            self = .portrait
        case .portraitUpsideDown:
            self = .portraitUpsideDown
        case .landscapeLeft:
            self = .landscapeRight
        case .landscapeRight:
            self = .landscapeLeft
        default:
            return nil
        }
    }
}
