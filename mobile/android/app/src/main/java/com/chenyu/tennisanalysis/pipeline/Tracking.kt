package com.chenyu.tennisanalysis.pipeline

import android.graphics.PointF
import android.graphics.RectF
import kotlin.math.abs
import kotlin.math.max

class SortTracker(
    private val maxAge: Int = 8,
    private val minHits: Int = 2,
    private val iouThreshold: Float = 0.2f
) {
    private data class TrackState(
        val id: Int,
        var bbox: RectF,
        var score: Float,
        var hits: Int,
        var missed: Int,
        var lastTimestampNs: Long,
        var velocity: PointF?
    )

    private val tracks = mutableListOf<TrackState>()
    private var nextTrackId = 1

    fun update(detections: List<Detection>, timestampNs: Long): List<TrackedObject> {
        val unmatchedTracks = tracks.toMutableSet()
        val unmatchedDetections = detections.toMutableList()

        detections.sortedByDescending { it.score }.forEach { detection ->
            val bestTrack = unmatchedTracks.maxByOrNull { iou(it.bbox, detection.bbox) }
            val bestIou = bestTrack?.let { iou(it.bbox, detection.bbox) } ?: 0f
            if (bestTrack != null && bestIou >= iouThreshold) {
                val previousCenter = centerOf(bestTrack.bbox)
                val nextCenter = centerOf(detection.bbox)
                val dtSeconds = ((timestampNs - bestTrack.lastTimestampNs).coerceAtLeast(1L)) / 1_000_000_000f
                bestTrack.velocity = PointF(
                    (nextCenter.x - previousCenter.x) / dtSeconds,
                    (nextCenter.y - previousCenter.y) / dtSeconds
                )
                bestTrack.bbox = RectF(detection.bbox)
                bestTrack.score = detection.score
                bestTrack.hits += 1
                bestTrack.missed = 0
                bestTrack.lastTimestampNs = timestampNs
                unmatchedTracks.remove(bestTrack)
                unmatchedDetections.remove(detection)
            }
        }

        unmatchedTracks.forEach { track ->
            track.missed += 1
            track.lastTimestampNs = timestampNs
        }

        unmatchedDetections.forEach { detection ->
            tracks += TrackState(
                id = nextTrackId++,
                bbox = RectF(detection.bbox),
                score = detection.score,
                hits = 1,
                missed = 0,
                lastTimestampNs = timestampNs,
                velocity = null
            )
        }

        tracks.removeAll { it.missed > maxAge }

        return tracks
            .filter { it.hits >= minHits || it.missed == 0 }
            .sortedByDescending { it.score * it.bbox.width() * it.bbox.height() }
            .take(2)
            .map { track ->
                TrackedObject(
                    trackId = track.id,
                    classId = 0,
                    score = track.score,
                    bbox = RectF(track.bbox),
                    center = centerOf(track.bbox),
                    velocity = track.velocity,
                    timestampNs = timestampNs
                )
            }
    }
}

class BallTrackFilter(
    private val maxLostFrames: Int = 5
) {
    private var lastBall: TrackedObject? = null
    private var lostFrames = 0

    fun update(detections: List<Detection>, timestampNs: Long): TrackedObject? {
        val bestDetection = if (lastBall == null) {
            detections.maxByOrNull { it.score }
        } else {
            detections.minByOrNull { distance(centerOf(it.bbox), lastBall!!.center) - (it.score * 50f) }
        }

        if (bestDetection == null) {
            lostFrames += 1
            if (lostFrames > maxLostFrames) {
                lastBall = null
            }
            return lastBall
        }

        val previousBall = lastBall
        val nextCenter = centerOf(bestDetection.bbox)
        val velocity = previousBall?.let {
            val dtSeconds = ((timestampNs - it.timestampNs).coerceAtLeast(1L)) / 1_000_000_000f
            PointF(
                (nextCenter.x - it.center.x) / dtSeconds,
                (nextCenter.y - it.center.y) / dtSeconds
            )
        }
        val smoothedRect = previousBall?.bbox?.let { smoothRect(it, bestDetection.bbox) } ?: bestDetection.bbox

        lastBall = TrackedObject(
            trackId = 1,
            classId = bestDetection.classId,
            score = bestDetection.score,
            bbox = smoothedRect,
            center = centerOf(smoothedRect),
            velocity = velocity,
            timestampNs = timestampNs
        )
        lostFrames = 0
        return lastBall
    }

    private fun smoothRect(previous: RectF, current: RectF): RectF {
        val alpha = 0.65f
        return RectF(
            previous.left * alpha + current.left * (1f - alpha),
            previous.top * alpha + current.top * (1f - alpha),
            previous.right * alpha + current.right * (1f - alpha),
            previous.bottom * alpha + current.bottom * (1f - alpha)
        )
    }
}

class ShotEventEngine {
    private val history = ArrayDeque<Pair<Long, PointF>>()
    private var lastEventTimestampNs = 0L

    fun update(input: ShotEventInput, timestampNs: Long): List<ShotEvent> {
        val ballCenter = input.ball?.center ?: return emptyList()
        history.addLast(timestampNs to ballCenter)
        while (history.size > 10) {
            history.removeFirst()
        }
        if (history.size < 4) {
            return emptyList()
        }

        val first = history.elementAt(history.size - 4)
        val middle = history.elementAt(history.size - 2)
        val last = history.last()
        val v1 = (middle.second.y - first.second.y) / ((middle.first - first.first).coerceAtLeast(1L) / 1_000_000_000f)
        val v2 = (last.second.y - middle.second.y) / ((last.first - middle.first).coerceAtLeast(1L) / 1_000_000_000f)

        if (abs(v1) < 80f || abs(v2) < 80f || v1 * v2 > 0f) {
            return emptyList()
        }
        if (timestampNs - lastEventTimestampNs < 250_000_000L) {
            return emptyList()
        }

        lastEventTimestampNs = timestampNs
        val nearestPlayer = input.players.minByOrNull { distance(it.center, ballCenter) }
        val isNearPlayer = nearestPlayer?.let {
            distance(it.center, ballCenter) < max(it.bbox.width(), it.bbox.height())
        } == true
        val eventType = if (isNearPlayer) ShotEventType.HIT_CONFIRMED else ShotEventType.HIT_CANDIDATE
        return listOf(
            ShotEvent(
                type = eventType,
                timestampNs = timestampNs,
                confidence = if (isNearPlayer) 0.85f else 0.55f
            )
        )
    }
}

class StatsAccumulator {
    private var stats = PlayerStats()
    private var lastBall: TrackedObject? = null
    private val lastPlayerCenters = mutableMapOf<Int, PointF>()

    fun update(input: StatsInput, timestampNs: Long): PlayerStats {
        val currentBall = input.ball
        val lastBallSnapshot = lastBall
        val ballSpeedKmh = if (currentBall != null && lastBallSnapshot != null) {
            val dtSeconds = ((timestampNs - lastBallSnapshot.timestampNs).coerceAtLeast(1L)) / 1_000_000_000f
            distance(currentBall.center, lastBallSnapshot.center) / dtSeconds * 0.036f
        } else {
            0f
        }

        var player1Distance = stats.player1DistanceM
        var player2Distance = stats.player2DistanceM
        input.players.forEachIndexed { index, player ->
            val lastCenter = lastPlayerCenters[player.trackId]
            if (lastCenter != null) {
                val delta = distance(lastCenter, player.center) * 0.002f
                if (index == 0) {
                    player1Distance += delta
                } else if (index == 1) {
                    player2Distance += delta
                }
            }
            lastPlayerCenters[player.trackId] = PointF(player.center.x, player.center.y)
        }

        val confirmedHit = input.events.firstOrNull { it.type == ShotEventType.HIT_CONFIRMED }
        stats = when {
            confirmedHit != null && input.players.isNotEmpty() -> {
                val hitter = input.players.minByOrNull { player ->
                    currentBall?.let { distance(player.center, it.center) } ?: Float.MAX_VALUE
                }
                if (hitter == input.players.first()) {
                    stats.copy(
                        player1ShotCount = stats.player1ShotCount + 1,
                        player1LastShotSpeedKmh = ballSpeedKmh,
                        player1DistanceM = player1Distance,
                        player2DistanceM = player2Distance
                    )
                } else {
                    stats.copy(
                        player2ShotCount = stats.player2ShotCount + 1,
                        player2LastShotSpeedKmh = ballSpeedKmh,
                        player1DistanceM = player1Distance,
                        player2DistanceM = player2Distance
                    )
                }
            }

            else -> stats.copy(
                player1DistanceM = player1Distance,
                player2DistanceM = player2Distance
            )
        }

        lastBall = currentBall
        return stats
    }
}

object BallRoiBuilder {
    fun build(lastBallBox: RectF?, court: CourtKeypointSet?): RectF? {
        if (lastBallBox != null) {
            val paddingX = lastBallBox.width() * 4f
            val paddingY = lastBallBox.height() * 4f
            return RectF(
                lastBallBox.left - paddingX,
                lastBallBox.top - paddingY,
                lastBallBox.right + paddingX,
                lastBallBox.bottom + paddingY
            )
        }

        val points = court?.points ?: return null
        if (points.isEmpty()) {
            return null
        }
        val minX = points.minOf { it.x }
        val minY = points.minOf { it.y }
        val maxX = points.maxOf { it.x }
        val maxY = points.maxOf { it.y }
        return RectF(minX, minY, maxX, maxY)
    }
}
