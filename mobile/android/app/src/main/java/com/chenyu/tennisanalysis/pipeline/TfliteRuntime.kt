package com.chenyu.tennisanalysis.pipeline

import android.content.Context
import android.graphics.Bitmap
import org.json.JSONArray
import org.json.JSONObject
import org.tensorflow.lite.Delegate
import org.tensorflow.lite.Interpreter
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel

object ModelMetadataLoader {
    fun load(context: Context, assetName: String?): ModelMetadata? {
        if (assetName.isNullOrBlank()) {
            return null
        }
        return runCatching {
            context.assets.open(assetName).bufferedReader().use { reader ->
                parse(reader.readText())
            }
        }.getOrNull()
    }

    private fun parse(rawJson: String): ModelMetadata {
        val json = JSONObject(rawJson)
        return ModelMetadata(
            inputShape = json.optJSONArray("input_shape").toIntList(),
            outputShape = json.optJSONArray("output_shape").toIntList(),
            inputLayout = json.optString("input_layout").ifBlank { null },
            inputRange = json.optJSONArray("input_range").toFloatList(),
            normalizeMean = json.optJSONArray("normalize_mean").toFloatList(),
            normalizeStd = json.optJSONArray("normalize_std").toFloatList(),
            trackedClassIds = json.optJSONArray("tracked_class_ids").toIntList().toSet()
        )
    }
}

abstract class BaseTfliteModel(
    context: Context,
    protected val config: DetectorConfig
) {
    protected val metadata = ModelMetadataLoader.load(
        context = context,
        assetName = config.metadataAssetName ?: config.assetFileName.substringBeforeLast('.') + ".json"
    )
    protected val trackedClassIds: Set<Int> = metadata?.trackedClassIds?.takeIf { it.isNotEmpty() } ?: config.trackedClassIds
    protected val inputSpec: InputSpec = resolveInputSpec()
    private val gpuDelegate: AutoCloseable?
    protected val interpreter: Interpreter?

    init {
        val delegateBundle = createInterpreter(context, config.assetFileName, config.runtimeConfig)
        gpuDelegate = delegateBundle?.second
        interpreter = delegateBundle?.first
    }

    private fun createInterpreter(
        context: Context,
        assetFileName: String,
        runtimeConfig: RuntimeConfig
    ): Pair<Interpreter, AutoCloseable?>? {
        return runCatching {
            val mappedBuffer = loadModelBuffer(context, assetFileName)
            val options = Interpreter.Options().apply {
                setNumThreads(runtimeConfig.numThreads)
            }

            val delegate = maybeCreateGpuDelegate(runtimeConfig.preferredDelegate)
            if (delegate != null) {
                options.addDelegate(delegate.first)
            }

            Interpreter(mappedBuffer, options) to delegate?.second
        }.getOrNull()
    }

    private fun loadModelBuffer(context: Context, assetFileName: String): ByteBuffer {
        context.assets.openFd(assetFileName).use { fileDescriptor ->
            FileInputStream(fileDescriptor.fileDescriptor).channel.use { channel ->
                return channel.map(
                    FileChannel.MapMode.READ_ONLY,
                    fileDescriptor.startOffset,
                    fileDescriptor.declaredLength
                )
            }
        }
    }

    private fun resolveInputSpec(): InputSpec {
        val shape = metadata?.inputShape ?: emptyList()
        val layout = metadata?.inputLayout?.uppercase() ?: "NCHW"
        return when {
            shape.size == 4 && layout == "NHWC" -> InputSpec(
                width = shape[2].takeIf { it > 0 } ?: config.inputWidth,
                height = shape[1].takeIf { it > 0 } ?: config.inputHeight,
                layout = layout
            )

            shape.size == 4 -> InputSpec(
                width = shape[3].takeIf { it > 0 } ?: config.inputWidth,
                height = shape[2].takeIf { it > 0 } ?: config.inputHeight,
                layout = layout
            )

            else -> InputSpec(
                width = config.inputWidth,
                height = config.inputHeight,
                layout = layout
            )
        }
    }

    protected fun createRgbInput(bitmap: Bitmap): ByteBuffer {
        val resized = Bitmap.createScaledBitmap(bitmap, inputSpec.width, inputSpec.height, true)
        val input = ByteBuffer.allocateDirect(inputSpec.width * inputSpec.height * 3 * 4)
        input.order(ByteOrder.nativeOrder())
        val pixels = IntArray(inputSpec.width * inputSpec.height).also {
            resized.getPixels(it, 0, inputSpec.width, 0, 0, inputSpec.width, inputSpec.height)
        }

        if (inputSpec.layout == "NHWC") {
            for (pixel in pixels) {
                input.putFloat(((pixel shr 16) and 0xFF) / 255f)
                input.putFloat(((pixel shr 8) and 0xFF) / 255f)
                input.putFloat((pixel and 0xFF) / 255f)
            }
        } else {
            for (channel in 0..2) {
                for (pixel in pixels) {
                    val value = when (channel) {
                        0 -> ((pixel shr 16) and 0xFF) / 255f
                        1 -> ((pixel shr 8) and 0xFF) / 255f
                        else -> (pixel and 0xFF) / 255f
                    }
                    input.putFloat(value)
                }
            }
        }

        if (resized !== bitmap) {
            resized.recycle()
        }
        input.rewind()
        return input
    }

    protected fun createNormalizedInput(bitmap: Bitmap): ByteBuffer {
        val mean = metadata?.normalizeMean?.takeIf { it.size == 3 }?.toFloatArray()
            ?: floatArrayOf(0.485f, 0.456f, 0.406f)
        val std = metadata?.normalizeStd?.takeIf { it.size == 3 }?.toFloatArray()
            ?: floatArrayOf(0.229f, 0.224f, 0.225f)
        val resized = Bitmap.createScaledBitmap(bitmap, inputSpec.width, inputSpec.height, true)
        val input = ByteBuffer.allocateDirect(inputSpec.width * inputSpec.height * 3 * 4)
        input.order(ByteOrder.nativeOrder())
        val pixels = IntArray(inputSpec.width * inputSpec.height).also {
            resized.getPixels(it, 0, inputSpec.width, 0, 0, inputSpec.width, inputSpec.height)
        }

        if (inputSpec.layout == "NHWC") {
            for (pixel in pixels) {
                val r = (((pixel shr 16) and 0xFF) / 255f - mean[0]) / std[0]
                val g = (((pixel shr 8) and 0xFF) / 255f - mean[1]) / std[1]
                val b = (((pixel) and 0xFF) / 255f - mean[2]) / std[2]
                input.putFloat(r)
                input.putFloat(g)
                input.putFloat(b)
            }
        } else {
            for (channel in 0..2) {
                for (pixel in pixels) {
                    val value = when (channel) {
                        0 -> ((pixel shr 16) and 0xFF) / 255f
                        1 -> ((pixel shr 8) and 0xFF) / 255f
                        else -> (pixel and 0xFF) / 255f
                    }
                    input.putFloat((value - mean[channel]) / std[channel])
                }
            }
        }

        if (resized !== bitmap) {
            resized.recycle()
        }
        input.rewind()
        return input
    }

    protected fun allocateFloatOutput(): Pair<ByteBuffer, IntArray>? {
        val outputTensor = interpreter?.getOutputTensor(0) ?: return null
        val shape = outputTensor.shape()
        val size = shape.fold(1) { acc, dimension -> acc * dimension }
        return ByteBuffer.allocateDirect(size * 4).apply {
            order(ByteOrder.nativeOrder())
        } to shape
    }

    protected fun readFloatOutput(outputBuffer: ByteBuffer, shape: IntArray): FloatArray {
        outputBuffer.rewind()
        val size = shape.fold(1) { acc, dimension -> acc * dimension }
        return FloatArray(size).also { outputBuffer.asFloatBuffer().get(it) }
    }

    fun close() {
        interpreter?.close()
        gpuDelegate?.close()
    }

    private fun maybeCreateGpuDelegate(preference: DelegatePreference): Pair<Delegate, AutoCloseable>? {
        if (preference == DelegatePreference.CPU) {
            return null
        }

        return runCatching {
            val compatibilityClass = Class.forName("org.tensorflow.lite.gpu.CompatibilityList")
            val compatibility = compatibilityClass.getDeclaredConstructor().newInstance()
            val isSupported = compatibilityClass.getMethod("isDelegateSupportedOnThisDevice").invoke(compatibility) as? Boolean
                ?: false
            if (!isSupported) {
                return null
            }

            val options = compatibilityClass.getMethod("getBestOptionsForThisDevice").invoke(compatibility)
            val delegateClass = Class.forName("org.tensorflow.lite.gpu.GpuDelegate")
            val delegate = delegateClass.getConstructor(options.javaClass).newInstance(options)
            @Suppress("UNCHECKED_CAST")
            (delegate as Delegate) to (delegate as AutoCloseable)
        }.getOrNull()
    }
}

private fun JSONArray?.toIntList(): List<Int> {
    if (this == null) {
        return emptyList()
    }
    return buildList(length()) {
        for (index in 0 until length()) {
            add(optInt(index))
        }
    }
}

private fun JSONArray?.toFloatList(): List<Float> {
    if (this == null) {
        return emptyList()
    }
    return buildList(length()) {
        for (index in 0 until length()) {
            add(optDouble(index).toFloat())
        }
    }
}
