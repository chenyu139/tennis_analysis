package com.chenyu.tennisanalysis.pipeline

import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.PixelFormat
import androidx.camera.core.ImageProxy
import java.nio.ByteBuffer

object ImageProxyConverter {
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
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val rowStride = plane.rowStride
        val pixelStride = plane.pixelStride
        val sourceBuffer = plane.buffer.duplicate().apply { rewind() }
        return if (rowStride == width * 4 && pixelStride == 4) {
            bitmap.copyPixelsFromBuffer(sourceBuffer)
            bitmap
        } else {
            val packed = ByteArray(width * height * 4)
            var targetOffset = 0
            for (row in 0 until height) {
                val rowBuffer = ByteArray(rowStride)
                sourceBuffer.position(row * rowStride)
                sourceBuffer.get(rowBuffer, 0, rowStride)
                var sourceOffset = 0
                repeat(width) {
                    packed[targetOffset] = rowBuffer[sourceOffset]
                    packed[targetOffset + 1] = rowBuffer[sourceOffset + 1]
                    packed[targetOffset + 2] = rowBuffer[sourceOffset + 2]
                    packed[targetOffset + 3] = rowBuffer[sourceOffset + 3]
                    targetOffset += 4
                    sourceOffset += pixelStride
                }
            }
            bitmap.copyPixelsFromBuffer(ByteBuffer.wrap(packed))
            bitmap
        }
    }

    private fun rotateBitmap(bitmap: Bitmap, degrees: Float): Bitmap {
        val matrix = Matrix().apply { postRotate(degrees) }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }
}
