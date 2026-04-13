package com.chenyu.tennisanalysis.pipeline

import android.graphics.PointF
import android.graphics.RectF
import kotlin.math.max
import kotlin.math.sqrt

fun centerOf(rect: RectF): PointF = PointF((rect.left + rect.right) / 2f, (rect.top + rect.bottom) / 2f)

fun distance(a: PointF, b: PointF): Float {
    val dx = a.x - b.x
    val dy = a.y - b.y
    return sqrt(dx * dx + dy * dy)
}

fun iou(a: RectF, b: RectF): Float {
    val left = max(a.left, b.left)
    val top = max(a.top, b.top)
    val right = minOf(a.right, b.right)
    val bottom = minOf(a.bottom, b.bottom)
    val intersectionWidth = (right - left).coerceAtLeast(0f)
    val intersectionHeight = (bottom - top).coerceAtLeast(0f)
    val intersection = intersectionWidth * intersectionHeight
    val union = a.width() * a.height() + b.width() * b.height() - intersection
    return if (union <= 0f) 0f else intersection / union
}
