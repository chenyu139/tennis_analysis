package com.chenyu.tennisanalysis.pipeline

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Matrix
import android.graphics.PixelFormat
import androidx.camera.core.ImageProxy
import java.nio.ByteBuffer

object ImageProxyConverter {
    private var sourceBitmap: Bitmap? = null
    private var rotatedBitmap: Bitmap? = null
    private var rowScratch = ByteArray(0)
    private var packedScratch = ByteArray(0)
    private val rotationMatrix = Matrix()
    private var rotationCanvas: Canvas? = null

    fun toBitmap(image: ImageProxy): Bitmap? {
        val bitmap = if (image.format == PixelFormat.RGBA_8888) {
            rgba8888ToBitmap(image)
        } else {
            null
        } ?: return null
        return when (image.imageInfo.rotationDegrees) {
            90 -> rotateBitmap(bitmap, 90f)
            180 -> rotateBitmap(bitmap, 180f)
            270 -> rotateBitmap(bitmap, 270f)
            else -> bitmap
        }
    }

    private fun rgba8888ToBitmap(image: ImageProxy): Bitmap? {
        val plane = image.planes.firstOrNull() ?: return null
        val width = image.width
        val height = image.height
        val bitmap = ensureBitmap(width, height, rotated = false)
        val rowStride = plane.rowStride
        val pixelStride = plane.pixelStride
        val sourceBuffer = plane.buffer.duplicate().apply { rewind() }
        return if (rowStride == width * 4 && pixelStride == 4) {
            bitmap.copyPixelsFromBuffer(sourceBuffer)
            bitmap
        } else {
            val packedSize = width * height * 4
            if (packedScratch.size < packedSize) {
                packedScratch = ByteArray(packedSize)
            }
            if (rowScratch.size < rowStride) {
                rowScratch = ByteArray(rowStride)
            }
            var targetOffset = 0
            for (row in 0 until height) {
                sourceBuffer.position(row * rowStride)
                sourceBuffer.get(rowScratch, 0, rowStride)
                var sourceOffset = 0
                repeat(width) {
                    packedScratch[targetOffset] = rowScratch[sourceOffset]
                    packedScratch[targetOffset + 1] = rowScratch[sourceOffset + 1]
                    packedScratch[targetOffset + 2] = rowScratch[sourceOffset + 2]
                    packedScratch[targetOffset + 3] = rowScratch[sourceOffset + 3]
                    targetOffset += 4
                    sourceOffset += pixelStride
                }
            }
            bitmap.copyPixelsFromBuffer(ByteBuffer.wrap(packedScratch, 0, packedSize))
            bitmap
        }
    }

    private fun rotateBitmap(bitmap: Bitmap, degrees: Float): Bitmap {
        if (degrees == 0f) {
            return bitmap
        }
        val destWidth = if (degrees == 90f || degrees == 270f) bitmap.height else bitmap.width
        val destHeight = if (degrees == 90f || degrees == 270f) bitmap.width else bitmap.height
        val destination = ensureBitmap(destWidth, destHeight, rotated = true)
        destination.eraseColor(0)
        val canvas = ensureRotationCanvas(destination)
        canvas.save()
        when (degrees) {
            90f -> {
                canvas.translate(destWidth.toFloat(), 0f)
                canvas.rotate(90f)
            }

            180f -> {
                canvas.translate(destWidth.toFloat(), destHeight.toFloat())
                canvas.rotate(180f)
            }

            270f -> {
                canvas.translate(0f, destHeight.toFloat())
                canvas.rotate(-90f)
            }
        }
        canvas.drawBitmap(bitmap, rotationMatrix, null)
        canvas.restore()
        return destination
    }

    private fun ensureBitmap(width: Int, height: Int, rotated: Boolean): Bitmap {
        val current = if (rotated) rotatedBitmap else sourceBitmap
        if (current?.width == width && current.height == height) {
            return current
        }
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        if (rotated) {
            rotatedBitmap = bitmap
            rotationCanvas = null
        } else {
            sourceBitmap = bitmap
        }
        return bitmap
    }

    private fun ensureRotationCanvas(bitmap: Bitmap): Canvas {
        val current = rotationCanvas
        if (current != null && current.width == bitmap.width && current.height == bitmap.height) {
            current.setBitmap(bitmap)
            return current
        }
        return Canvas(bitmap).also { rotationCanvas = it }
    }
}
