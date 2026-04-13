package com.chenyu.tennisanalysis

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Size
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.chenyu.tennisanalysis.pipeline.AnalyzerSettings
import com.chenyu.tennisanalysis.pipeline.BallDetector
import com.chenyu.tennisanalysis.pipeline.BallTrackFilter
import com.chenyu.tennisanalysis.pipeline.CameraFrameAnalyzer
import com.chenyu.tennisanalysis.pipeline.CourtKeypointDetector
import com.chenyu.tennisanalysis.pipeline.DelegatePreference
import com.chenyu.tennisanalysis.pipeline.DetectorConfig
import com.chenyu.tennisanalysis.pipeline.OverlayStateStore
import com.chenyu.tennisanalysis.pipeline.PlayerDetector
import com.chenyu.tennisanalysis.pipeline.RuntimeConfig
import com.chenyu.tennisanalysis.pipeline.ShotEventEngine
import com.chenyu.tennisanalysis.pipeline.SortTracker
import com.chenyu.tennisanalysis.pipeline.StatsAccumulator
import com.chenyu.tennisanalysis.ui.OverlayView
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private lateinit var previewView: PreviewView
    private lateinit var overlayHost: FrameLayout
    private lateinit var overlayView: OverlayView
    private lateinit var analysisExecutor: ExecutorService
    private lateinit var playerDetector: PlayerDetector
    private lateinit var ballDetector: BallDetector
    private lateinit var courtDetector: CourtKeypointDetector

    private val overlayStateStore = OverlayStateStore()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        previewView = findViewById(R.id.previewView)
        overlayHost = findViewById(R.id.overlayHost)
        overlayView = OverlayView(this)
        overlayHost.addView(
            overlayView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        overlayStateStore.addListener { frame ->
            runOnUiThread {
                overlayView.render(frame)
            }
        }

        analysisExecutor = Executors.newSingleThreadExecutor()
        playerDetector = PlayerDetector(
            context = this,
            config = DetectorConfig(
                assetFileName = "player_detector.tflite",
                inputWidth = 640,
                inputHeight = 640,
                confidenceThreshold = 0.2f,
                trackedClassIds = setOf(0),
                metadataAssetName = "player_detector.json",
                runtimeConfig = RuntimeConfig(
                    preferredDelegate = DelegatePreference.AUTO,
                    numThreads = 4
                )
            )
        )
        ballDetector = BallDetector(
            context = this,
            config = DetectorConfig(
                assetFileName = "ball_detector.tflite",
                inputWidth = 640,
                inputHeight = 640,
                confidenceThreshold = 0.15f,
                trackedClassIds = setOf(0),
                metadataAssetName = "ball_detector.json",
                runtimeConfig = RuntimeConfig(
                    preferredDelegate = DelegatePreference.AUTO,
                    numThreads = 4
                )
            )
        )
        courtDetector = CourtKeypointDetector(
            context = this,
            config = DetectorConfig(
                assetFileName = "court_keypoints.tflite",
                inputWidth = 224,
                inputHeight = 224,
                confidenceThreshold = 0f,
                metadataAssetName = "court_keypoints.json",
                runtimeConfig = RuntimeConfig(
                    preferredDelegate = DelegatePreference.CPU,
                    numThreads = 2
                )
            )
        )

        if (hasCameraPermission()) {
            startCamera()
        } else {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), CAMERA_REQUEST_CODE)
        }
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()

            val preview = Preview.Builder().build().apply {
                setSurfaceProvider(previewView.surfaceProvider)
            }

            val imageAnalysis = ImageAnalysis.Builder()
                .setTargetResolution(Size(960, 540))
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            val analyzer = CameraFrameAnalyzer(
                playerDetector = playerDetector,
                ballDetector = ballDetector,
                courtDetector = courtDetector,
                playerTracker = SortTracker(minHits = 1),
                ballTracker = BallTrackFilter(),
                shotEventEngine = ShotEventEngine(),
                statsAccumulator = StatsAccumulator(),
                overlayStateStore = overlayStateStore,
                settings = AnalyzerSettings(
                    playerFrameStride = 2,
                    ballFrameStride = 2,
                    courtFrameStride = 45,
                    enableBallDetection = false,
                    enableCourtDetection = false,
                    showPerformanceStats = true
                )
            )

            imageAnalysis.setAnalyzer(analysisExecutor, analyzer)

            cameraProvider.unbindAll()
            cameraProvider.bindToLifecycle(
                this,
                CameraSelector.DEFAULT_BACK_CAMERA,
                preview,
                imageAnalysis
            )
        }, ContextCompat.getMainExecutor(this))
    }

    private fun hasCameraPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_REQUEST_CODE && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startCamera()
        }
    }

    override fun onDestroy() {
        analysisExecutor.shutdown()
        overlayStateStore.clear()
        playerDetector.close()
        ballDetector.close()
        courtDetector.close()
        super.onDestroy()
    }

    companion object {
        private const val CAMERA_REQUEST_CODE = 1001
    }
}
