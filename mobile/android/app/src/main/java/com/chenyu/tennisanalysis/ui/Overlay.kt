package com.chenyu.tennisanalysis.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PointF
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import com.chenyu.tennisanalysis.pipeline.OverlayFrame
import com.chenyu.tennisanalysis.pipeline.PerformanceStats
import com.chenyu.tennisanalysis.pipeline.PlayerStats
import com.chenyu.tennisanalysis.pipeline.ShotEventType
import com.chenyu.tennisanalysis.pipeline.TrackedObject
import kotlin.math.max
import kotlin.math.min

class OverlayView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {
    private val renderer = OverlayRenderer()
    private var frame: OverlayFrame? = null

    fun render(overlayFrame: OverlayFrame) {
        frame = overlayFrame
        postInvalidateOnAnimation()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        frame?.let {
            renderer.draw(canvas, width.toFloat(), height.toFloat(), it)
        }
    }
}

private class OverlayRenderer {
    private val playerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#00E5FF")
        style = Paint.Style.STROKE
        strokeWidth = 6f
    }

    private val ballPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FFD600")
        style = Paint.Style.STROKE
        strokeWidth = 5f
    }

    private val pointPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#69F0AE")
        style = Paint.Style.FILL
    }

    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 34f
        style = Paint.Style.FILL
    }

    private val panelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(170, 0, 0, 0)
        style = Paint.Style.FILL
    }

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 3f
    }

    private val player1MiniPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#00E5FF")
        style = Paint.Style.FILL
    }

    private val player2MiniPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FF80AB")
        style = Paint.Style.FILL
    }

    private val ballMiniPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FFD600")
        style = Paint.Style.FILL
    }

    fun draw(canvas: Canvas, viewWidth: Float, viewHeight: Float, frame: OverlayFrame) {
        val mapper = CoordinateMapper(
            sourceWidth = frame.sourceWidth.toFloat(),
            sourceHeight = frame.sourceHeight.toFloat(),
            targetWidth = viewWidth,
            targetHeight = viewHeight
        )

        drawPlayers(canvas, frame.players, mapper)
        drawBall(canvas, frame.ball, mapper)
        drawCourt(canvas, frame.court?.points ?: emptyList(), mapper)
        drawEventTag(canvas, frame.events.lastOrNull()?.type)
        drawStats(canvas, frame.stats, viewWidth, viewHeight)
        drawMiniCourt(canvas, frame, viewWidth, viewHeight)
        drawPerformance(canvas, frame.performance, viewWidth)
    }

    private fun drawPlayers(canvas: Canvas, players: List<TrackedObject>, mapper: CoordinateMapper) {
        players.forEachIndexed { index, player ->
            val rect = mapper.mapRect(player.bbox)
            canvas.drawRect(rect, playerPaint)
            canvas.drawText("P${index + 1}", rect.left, rect.top - 10f, textPaint)
        }
    }

    private fun drawBall(canvas: Canvas, ball: TrackedObject?, mapper: CoordinateMapper) {
        val rect = ball?.bbox?.let { mapper.mapRect(it) } ?: return
        canvas.drawRect(rect, ballPaint)
        canvas.drawCircle(rect.centerX(), rect.centerY(), max(8f, rect.width() / 2f), pointPaint)
    }

    private fun drawCourt(canvas: Canvas, points: List<PointF>, mapper: CoordinateMapper) {
        points.forEachIndexed { index, point ->
            val mapped = mapper.mapPoint(point)
            canvas.drawCircle(mapped.x, mapped.y, 7f, pointPaint)
            canvas.drawText(index.toString(), mapped.x + 8f, mapped.y - 8f, textPaint)
        }
    }

    private fun drawEventTag(canvas: Canvas, eventType: ShotEventType?) {
        val label = when (eventType) {
            ShotEventType.HIT_CONFIRMED -> "HIT"
            ShotEventType.HIT_CANDIDATE -> "HIT?"
            ShotEventType.LOST_BALL -> "LOST"
            null -> return
        }
        val width = 180f
        val height = 72f
        val left = 24f
        val top = 24f
        canvas.drawRoundRect(RectF(left, top, left + width, top + height), 20f, 20f, panelPaint)
        canvas.drawText(label, left + 28f, top + 47f, textPaint)
    }

    private fun drawStats(canvas: Canvas, stats: PlayerStats, viewWidth: Float, viewHeight: Float) {
        val panelWidth = min(520f, viewWidth * 0.45f)
        val panelHeight = 220f
        val left = 24f
        val top = viewHeight - panelHeight - 24f
        canvas.drawRoundRect(RectF(left, top, left + panelWidth, top + panelHeight), 20f, 20f, panelPaint)

        val lines = listOf(
            "P1 shots ${stats.player1ShotCount}   speed ${stats.player1LastShotSpeedKmh.format1()} km/h",
            "P2 shots ${stats.player2ShotCount}   speed ${stats.player2LastShotSpeedKmh.format1()} km/h",
            "P1 move ${stats.player1DistanceM.format1()} m",
            "P2 move ${stats.player2DistanceM.format1()} m"
        )

        lines.forEachIndexed { index, line ->
            canvas.drawText(line, left + 24f, top + 48f + (index * 42f), textPaint)
        }
    }

    private fun drawMiniCourt(canvas: Canvas, frame: OverlayFrame, viewWidth: Float, viewHeight: Float) {
        val court = frame.court ?: return
        if (court.points.isEmpty()) {
            return
        }
        val panelWidth = min(300f, viewWidth * 0.28f)
        val panelHeight = panelWidth * 2f
        val left = viewWidth - panelWidth - 24f
        val top = viewHeight - panelHeight - 24f
        val rect = RectF(left, top, left + panelWidth, top + panelHeight)
        canvas.drawRoundRect(rect, 20f, 20f, panelPaint)

        val courtRect = RectF(left + 24f, top + 24f, left + panelWidth - 24f, top + panelHeight - 24f)
        canvas.drawRect(courtRect, linePaint)
        canvas.drawLine(courtRect.left, courtRect.centerY(), courtRect.right, courtRect.centerY(), linePaint)
        canvas.drawLine(courtRect.centerX(), courtRect.top, courtRect.centerX(), courtRect.bottom, linePaint)

        val bounds = boundsOf(court.points)
        frame.players.forEachIndexed { index, player ->
            val point = projectToMiniCourt(player.center, bounds, courtRect)
            val paint = if (index == 0) player1MiniPaint else player2MiniPaint
            canvas.drawCircle(point.x, point.y, 10f, paint)
            canvas.drawText("P${index + 1}", point.x + 12f, point.y - 12f, textPaint)
        }
        frame.ball?.let { ball ->
            val point = projectToMiniCourt(ball.center, bounds, courtRect)
            canvas.drawCircle(point.x, point.y, 8f, ballMiniPaint)
        }
    }

    private fun drawPerformance(canvas: Canvas, performance: PerformanceStats, viewWidth: Float) {
        if (performance.totalMs <= 0f) {
            return
        }
        val panelWidth = min(430f, viewWidth * 0.38f)
        val left = viewWidth - panelWidth - 24f
        val top = 24f
        val panelHeight = 190f
        canvas.drawRoundRect(RectF(left, top, left + panelWidth, top + panelHeight), 20f, 20f, panelPaint)
        val lines = listOf(
            "total ${performance.totalMs.format1()} ms",
            "convert ${performance.convertMs.format1()} ms",
            "player ${performance.playerMs.format1()} ms",
            "court ${performance.courtMs.format1()} ms",
            "ball ${performance.ballMs.format1()} ms"
        )
        lines.forEachIndexed { index, line ->
            canvas.drawText(line, left + 20f, top + 42f + index * 32f, textPaint)
        }
    }

    private fun boundsOf(points: List<PointF>): RectF {
        val minX = points.minOf { it.x }
        val minY = points.minOf { it.y }
        val maxX = points.maxOf { it.x }
        val maxY = points.maxOf { it.y }
        return RectF(minX, minY, maxX, maxY)
    }

    private fun projectToMiniCourt(point: PointF, source: RectF, target: RectF): PointF {
        val nx = ((point.x - source.left) / max(1f, source.width())).coerceIn(0f, 1f)
        val ny = ((point.y - source.top) / max(1f, source.height())).coerceIn(0f, 1f)
        return PointF(
            target.left + nx * target.width(),
            target.top + ny * target.height()
        )
    }
}

private class CoordinateMapper(
    sourceWidth: Float,
    sourceHeight: Float,
    targetWidth: Float,
    targetHeight: Float
) {
    // PreviewView uses fillCenter, so the overlay must apply the same center-crop transform.
    private val scale = max(targetWidth / sourceWidth, targetHeight / sourceHeight)
    private val offsetX = (targetWidth - sourceWidth * scale) / 2f
    private val offsetY = (targetHeight - sourceHeight * scale) / 2f

    fun mapRect(rect: RectF): RectF {
        return RectF(
            offsetX + rect.left * scale,
            offsetY + rect.top * scale,
            offsetX + rect.right * scale,
            offsetY + rect.bottom * scale
        )
    }

    fun mapPoint(point: PointF): PointF {
        return PointF(
            offsetX + point.x * scale,
            offsetY + point.y * scale
        )
    }
}

private fun Float.format1(): String {
    return String.format("%.1f", this)
}
