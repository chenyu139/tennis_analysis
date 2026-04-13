package com.chenyu.tennisanalysis.pipeline

import android.os.SystemClock
import android.graphics.RectF
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy

class CameraFrameAnalyzer(
    private val playerDetector: PlayerDetector,
    private val ballDetector: BallDetector,
    private val courtDetector: CourtKeypointDetector,
    private val playerTracker: SortTracker,
    private val ballTracker: BallTrackFilter,
    private val shotEventEngine: ShotEventEngine,
    private val statsAccumulator: StatsAccumulator,
    private val overlayStateStore: OverlayStateStore,
    private val settings: AnalyzerSettings
) : ImageAnalysis.Analyzer {
    private var frameIndex = 0
    private var lastCourt: CourtKeypointSet? = null
    private var lastBallBox: RectF? = null
    private var performanceStats = PerformanceStats()

    override fun analyze(image: ImageProxy) {
        val analyzeStartNs = SystemClock.elapsedRealtimeNanos()
        val bitmap = ImageProxyConverter.toBitmap(image)
        if (bitmap == null) {
            image.close()
            return
        }
        val afterConvertNs = SystemClock.elapsedRealtimeNanos()

        val timestampNs = image.imageInfo.timestamp
        val playerDetectStartNs = afterConvertNs
        val playerDetections = if (frameIndex % settings.playerFrameStride == 0) {
            playerDetector.detect(bitmap, timestampNs)
        } else {
            emptyList()
        }
        val afterPlayerNs = SystemClock.elapsedRealtimeNanos()
        val trackedPlayers = playerTracker.update(playerDetections, timestampNs)

        if (settings.enableCourtDetection && (frameIndex % settings.courtFrameStride == 0 || lastCourt == null)) {
            val candidateCourt = courtDetector.detect(bitmap, timestampNs)
            lastCourt = candidateCourt?.takeIf {
                isPlausibleCourt(
                    court = it,
                    sourceWidth = bitmap.width,
                    sourceHeight = bitmap.height,
                    playerDetections = playerDetections
                )
            } ?: lastCourt
        } else if (!settings.enableCourtDetection) {
            lastCourt = null
        }
        val afterCourtNs = SystemClock.elapsedRealtimeNanos()

        val ballDetections = if (settings.enableBallDetection && frameIndex % settings.ballFrameStride == 0) {
            ballDetector.detect(
                bitmap = bitmap,
                roi = BallRoiBuilder.build(lastBallBox, lastCourt),
                timestampNs = timestampNs
            )
        } else {
            emptyList()
        }
        val trackedBall = if (settings.enableBallDetection) {
            ballTracker.update(ballDetections, timestampNs)
        } else {
            null
        }
        lastBallBox = trackedBall?.bbox
        val afterBallNs = SystemClock.elapsedRealtimeNanos()

        val events = shotEventEngine.update(
            ShotEventInput(
                players = trackedPlayers,
                ball = trackedBall,
                court = lastCourt
            ),
            timestampNs
        )

        val stats = statsAccumulator.update(
            StatsInput(
                players = trackedPlayers,
                ball = trackedBall,
                events = events,
                court = lastCourt
            ),
            timestampNs
        )

        overlayStateStore.publish(
            OverlayFrame(
                timestampNs = timestampNs,
                sourceWidth = bitmap.width,
                sourceHeight = bitmap.height,
                players = trackedPlayers,
                ball = trackedBall,
                court = lastCourt,
                events = events,
                stats = stats,
                performance = if (settings.showPerformanceStats) {
                    updatePerformanceStats(
                        convertMs = nanosToMs(afterConvertNs - analyzeStartNs),
                        playerMs = nanosToMs(afterPlayerNs - playerDetectStartNs),
                        courtMs = nanosToMs(afterCourtNs - afterPlayerNs),
                        ballMs = nanosToMs(afterBallNs - afterCourtNs),
                        totalMs = nanosToMs(afterBallNs - analyzeStartNs)
                    )
                } else {
                    PerformanceStats()
                }
            )
        )

        frameIndex += 1
        bitmap.recycle()
        image.close()
    }

    private fun updatePerformanceStats(
        convertMs: Float,
        playerMs: Float,
        courtMs: Float,
        ballMs: Float,
        totalMs: Float
    ): PerformanceStats {
        performanceStats = PerformanceStats(
            totalMs = smooth(performanceStats.totalMs, totalMs),
            convertMs = smooth(performanceStats.convertMs, convertMs),
            playerMs = smooth(performanceStats.playerMs, playerMs),
            courtMs = smooth(performanceStats.courtMs, courtMs),
            ballMs = smooth(performanceStats.ballMs, ballMs)
        )
        return performanceStats
    }

    private fun smooth(previous: Float, current: Float): Float {
        return if (previous == 0f) current else previous * 0.8f + current * 0.2f
    }

    private fun nanosToMs(durationNs: Long): Float {
        return durationNs / 1_000_000f
    }

    private fun isPlausibleCourt(
        court: CourtKeypointSet,
        sourceWidth: Int,
        sourceHeight: Int,
        playerDetections: List<Detection>
    ): Boolean {
        if (court.points.size < 4) {
            return false
        }

        val allowedLeft = -sourceWidth * 0.05f
        val allowedTop = -sourceHeight * 0.05f
        val allowedRight = sourceWidth * 1.05f
        val allowedBottom = sourceHeight * 1.05f
        if (court.points.any { point ->
                point.x !in allowedLeft..allowedRight || point.y !in allowedTop..allowedBottom
            }
        ) {
            return false
        }

        val minX = court.points.minOf { it.x }
        val minY = court.points.minOf { it.y }
        val maxX = court.points.maxOf { it.x }
        val maxY = court.points.maxOf { it.y }
        val bounds = RectF(minX, minY, maxX, maxY)
        if (bounds.width() < sourceWidth * 0.35f || bounds.height() < sourceHeight * 0.2f) {
            return false
        }

        if (playerDetections.isEmpty()) {
            return false
        }

        val paddingX = bounds.width() * 0.15f
        val paddingY = bounds.height() * 0.15f
        val expanded = RectF(
            bounds.left - paddingX,
            bounds.top - paddingY,
            bounds.right + paddingX,
            bounds.bottom + paddingY
        )
        return playerDetections.any { detection ->
            expanded.contains(detection.bbox.centerX(), detection.bbox.centerY())
        }
    }
}
