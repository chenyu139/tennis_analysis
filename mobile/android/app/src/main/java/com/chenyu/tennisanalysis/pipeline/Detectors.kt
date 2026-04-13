package com.chenyu.tennisanalysis.pipeline

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PointF
import android.graphics.Rect
import android.graphics.RectF

abstract class BaseYoloDetector(
    context: Context,
    config: DetectorConfig
) : BaseTfliteModel(context, config) {
    protected fun runDetection(bitmap: Bitmap, roi: RectF?, timestampNs: Long): List<Detection> {
        val model = interpreter ?: return emptyList()
        val cropRect = roi?.toBoundedRect(bitmap.width, bitmap.height)
        val cropped = cropRect?.let {
            Bitmap.createBitmap(bitmap, it.left, it.top, it.width(), it.height())
        } ?: bitmap
        val input = createRgbInput(cropped)
        val outputInfo = allocateFloatOutput() ?: return emptyList()
        val outputBuffer = outputInfo.first
        model.run(input, outputBuffer)
        val detections = decodeYoloLikeOutput(
            outputArray = readFloatOutput(outputBuffer, outputInfo.second),
            outputShape = outputInfo.second,
            sourceWidth = cropped.width,
            sourceHeight = cropped.height,
            offsetX = cropRect?.left?.toFloat() ?: 0f,
            offsetY = cropRect?.top?.toFloat() ?: 0f,
            timestampNs = timestampNs
        )
        if (cropped !== bitmap) {
            cropped.recycle()
        }
        return detections
    }

    private fun decodeYoloLikeOutput(
        outputArray: FloatArray,
        outputShape: IntArray,
        sourceWidth: Int,
        sourceHeight: Int,
        offsetX: Float,
        offsetY: Float,
        timestampNs: Long
    ): List<Detection> {
        val shape = when (outputShape.size) {
            2 -> intArrayOf(1, outputShape[0], outputShape[1])
            3 -> outputShape
            else -> return emptyList()
        }
        val transposed = shape[1] < shape[2]
        val attrCount = if (transposed) shape[1] else shape[2]
        val candidateCount = if (transposed) shape[2] else shape[1]
        if (attrCount < 5) {
            return emptyList()
        }

        fun value(candidateIndex: Int, attributeIndex: Int): Float {
            return if (transposed) {
                outputArray[attributeIndex * candidateCount + candidateIndex]
            } else {
                outputArray[candidateIndex * attrCount + attributeIndex]
            }
        }

        val hasObjectness = attrCount == 6 || attrCount == 85
        val classStartIndex = if (hasObjectness) 5 else 4
        val classCount = attrCount - classStartIndex
        val detections = mutableListOf<Detection>()
        val normalizedCoordinates = run {
            var maxCoordinate = 0f
            val sampleCount = minOf(candidateCount, 64)
            for (candidateIndex in 0 until sampleCount) {
                maxCoordinate = maxOf(
                    maxCoordinate,
                    value(candidateIndex, 0),
                    value(candidateIndex, 1),
                    value(candidateIndex, 2),
                    value(candidateIndex, 3)
                )
            }
            maxCoordinate <= 2f
        }

        for (candidateIndex in 0 until candidateCount) {
            val cx = value(candidateIndex, 0)
            val cy = value(candidateIndex, 1)
            val w = value(candidateIndex, 2)
            val h = value(candidateIndex, 3)

            var bestClassId = 0
            var bestClassScore = if (classCount <= 0) value(candidateIndex, 4) else 0f
            if (classCount > 0) {
                for (classIndex in 0 until classCount) {
                    val candidateScore = value(candidateIndex, classStartIndex + classIndex)
                    if (candidateScore > bestClassScore) {
                        bestClassScore = candidateScore
                        bestClassId = classIndex
                    }
                }
            }

            val confidence = if (hasObjectness && classCount > 0) {
                value(candidateIndex, 4) * bestClassScore
            } else {
                bestClassScore
            }
            if (confidence < config.confidenceThreshold) {
                continue
            }
            if (trackedClassIds.isNotEmpty() && bestClassId !in trackedClassIds) {
                continue
            }

            val scaleX = if (normalizedCoordinates) sourceWidth.toFloat() else sourceWidth / inputSpec.width.toFloat()
            val scaleY = if (normalizedCoordinates) sourceHeight.toFloat() else sourceHeight / inputSpec.height.toFloat()
            val left = ((cx - (w / 2f)) * scaleX) + offsetX
            val top = ((cy - (h / 2f)) * scaleY) + offsetY
            val right = ((cx + (w / 2f)) * scaleX) + offsetX
            val bottom = ((cy + (h / 2f)) * scaleY) + offsetY
            val maxX = offsetX + sourceWidth
            val maxY = offsetY + sourceHeight
            val rect = RectF(
                left.coerceIn(0f, maxX),
                top.coerceIn(0f, maxY),
                right.coerceIn(0f, maxX),
                bottom.coerceIn(0f, maxY)
            )
            if (rect.width() <= 2f || rect.height() <= 2f) {
                continue
            }

            detections += Detection(
                classId = bestClassId,
                score = confidence,
                bbox = rect,
                timestampNs = timestampNs
            )
        }

        return nonMaximumSuppression(detections, config.iouThreshold)
    }
}

class PlayerDetector(
    context: Context,
    config: DetectorConfig
) : BaseYoloDetector(context, config) {
    fun detect(bitmap: Bitmap, timestampNs: Long): List<Detection> {
        return runDetection(bitmap = bitmap, roi = null, timestampNs = timestampNs)
    }
}

class BallDetector(
    context: Context,
    config: DetectorConfig
) : BaseYoloDetector(context, config) {
    fun detect(bitmap: Bitmap, roi: RectF?, timestampNs: Long): List<Detection> {
        return runDetection(bitmap = bitmap, roi = roi, timestampNs = timestampNs)
    }
}

class CourtKeypointDetector(
    context: Context,
    config: DetectorConfig
) : BaseTfliteModel(context, config) {
    fun detect(bitmap: Bitmap, timestampNs: Long): CourtKeypointSet? {
        val model = interpreter ?: return null
        val input = createNormalizedInput(bitmap)
        val outputInfo = allocateFloatOutput() ?: return null
        val outputBuffer = outputInfo.first
        model.run(input, outputBuffer)
        val pointValues = alignCourtOutput(readFloatOutput(outputBuffer, outputInfo.second), outputInfo.second)
        if (pointValues.size < 28) {
            return null
        }

        val points = buildList(14) {
            for (index in 0 until 14) {
                val x = pointValues[index * 2] * bitmap.width / inputSpec.width
                val y = pointValues[index * 2 + 1] * bitmap.height / inputSpec.height
                add(PointF(x, y))
            }
        }

        return CourtKeypointSet(
            points = points,
            confidence = 1f,
            timestampNs = timestampNs
        )
    }

    private fun alignCourtOutput(outputArray: FloatArray, runtimeShape: IntArray): FloatArray {
        val metadataShape = metadata?.outputShape ?: emptyList()
        val flattened = when {
            runtimeShape.contentEquals(intArrayOf(1, 14, 2)) || metadataShape == listOf(1, 14, 2) -> {
                FloatArray(28) { index ->
                    val pointIndex = index / 2
                    val axis = index % 2
                    outputArray[pointIndex * 2 + axis]
                }
            }

            runtimeShape.contentEquals(intArrayOf(1, 2, 14)) || metadataShape == listOf(1, 2, 14) -> {
                FloatArray(28) { index ->
                    val pointIndex = index / 2
                    val axis = index % 2
                    outputArray[axis * 14 + pointIndex]
                }
            }

            else -> outputArray
        }
        return flattened
    }
}

private fun RectF.toBoundedRect(maxWidth: Int, maxHeight: Int): Rect {
    val safeLeft = left.toInt().coerceIn(0, maxWidth - 1)
    val safeTop = top.toInt().coerceIn(0, maxHeight - 1)
    val safeRight = right.toInt().coerceIn(safeLeft + 1, maxWidth)
    val safeBottom = bottom.toInt().coerceIn(safeTop + 1, maxHeight)
    return Rect(safeLeft, safeTop, safeRight, safeBottom)
}

private fun nonMaximumSuppression(detections: List<Detection>, iouThreshold: Float): List<Detection> {
    val sorted = detections.sortedByDescending { it.score }.toMutableList()
    val selected = mutableListOf<Detection>()
    while (sorted.isNotEmpty()) {
        val current = sorted.removeAt(0)
        selected += current
        sorted.removeAll { candidate ->
            candidate.classId == current.classId && iou(candidate.bbox, current.bbox) >= iouThreshold
        }
    }
    return selected
}
