package com.chenyu.tennisanalysis.pipeline

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import org.json.JSONArray
import org.json.JSONObject
import org.tensorflow.lite.DataType
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
    private val inputTensorInfo: TensorInfo?
    private val outputTensorInfo: TensorInfo?
    private val resizePaint = Paint(Paint.FILTER_BITMAP_FLAG)
    private val resizeDstRect = Rect(0, 0, inputSpec.width, inputSpec.height)
    private var inputBitmap: Bitmap? = null
    private var inputCanvas: Canvas? = null
    private var inputPixels = IntArray(inputSpec.width * inputSpec.height)
    private var rgbInputBuffer: ByteBuffer? = null
    private var normalizedInputBuffer: ByteBuffer? = null
    private val outputInfo by lazy { allocateFloatOutput() }

    init {
        val delegateBundle = createInterpreter(context, config.assetFileName, config.runtimeConfig)
        gpuDelegate = delegateBundle?.second
        interpreter = delegateBundle?.first
        inputTensorInfo = interpreter?.getInputTensor(0)?.toTensorInfo()
        outputTensorInfo = interpreter?.getOutputTensor(0)?.toTensorInfo()
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
                setUseXNNPACK(runtimeConfig.preferredDelegate != DelegatePreference.NNAPI)
            }

            val delegate = maybeCreateDelegate(runtimeConfig.preferredDelegate)
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
        val pixels = readResizedPixels(bitmap)
        val tensorInfo = inputTensorInfo
        val input = ensureInputBuffer(normalized = false).apply { rewind() }
        val inputValueScale = resolveRgbInputValueScale()

        if (inputSpec.layout == "NHWC") {
            for (pixel in pixels) {
                input.putTensorValue(((pixel shr 16) and 0xFF) / inputValueScale, tensorInfo)
                input.putTensorValue(((pixel shr 8) and 0xFF) / inputValueScale, tensorInfo)
                input.putTensorValue((pixel and 0xFF) / inputValueScale, tensorInfo)
            }
        } else {
            for (channel in 0..2) {
                for (pixel in pixels) {
                    val value = when (channel) {
                        0 -> ((pixel shr 16) and 0xFF) / inputValueScale
                        1 -> ((pixel shr 8) and 0xFF) / inputValueScale
                        else -> (pixel and 0xFF) / inputValueScale
                    }
                    input.putTensorValue(value, tensorInfo)
                }
            }
        }
        input.rewind()
        return input
    }

    protected fun createNormalizedInput(bitmap: Bitmap): ByteBuffer {
        val tensorInfo = inputTensorInfo
        val mean = metadata?.normalizeMean?.takeIf { it.size == 3 }?.toFloatArray()
            ?: floatArrayOf(0.485f, 0.456f, 0.406f)
        val std = metadata?.normalizeStd?.takeIf { it.size == 3 }?.toFloatArray()
            ?: floatArrayOf(0.229f, 0.224f, 0.225f)
        val pixels = readResizedPixels(bitmap)
        val input = ensureInputBuffer(normalized = true).apply { rewind() }

        if (inputSpec.layout == "NHWC") {
            for (pixel in pixels) {
                val r = (((pixel shr 16) and 0xFF) / 255f - mean[0]) / std[0]
                val g = (((pixel shr 8) and 0xFF) / 255f - mean[1]) / std[1]
                val b = (((pixel) and 0xFF) / 255f - mean[2]) / std[2]
                input.putTensorValue(r, tensorInfo)
                input.putTensorValue(g, tensorInfo)
                input.putTensorValue(b, tensorInfo)
            }
        } else {
            for (channel in 0..2) {
                for (pixel in pixels) {
                    val value = when (channel) {
                        0 -> ((pixel shr 16) and 0xFF) / 255f
                        1 -> ((pixel shr 8) and 0xFF) / 255f
                        else -> (pixel and 0xFF) / 255f
                    }
                    input.putTensorValue((value - mean[channel]) / std[channel], tensorInfo)
                }
            }
        }
        input.rewind()
        return input
    }

    protected fun allocateFloatOutput(): Pair<ByteBuffer, IntArray>? {
        val tensorInfo = outputTensorInfo ?: return null
        return ByteBuffer.allocateDirect(tensorInfo.numBytes).apply {
            order(ByteOrder.nativeOrder())
        } to tensorInfo.shape
    }

    protected fun readFloatOutput(outputBuffer: ByteBuffer, shape: IntArray): FloatArray {
        outputBuffer.rewind()
        val size = shape.fold(1) { acc, dimension -> acc * dimension }
        val tensorInfo = outputTensorInfo ?: return FloatArray(size)
        return when (tensorInfo.dataType) {
            DataType.FLOAT32 -> FloatArray(size).also { outputBuffer.asFloatBuffer().get(it) }
            DataType.UINT8 -> FloatArray(size) { index ->
                val raw = outputBuffer.get(index).toInt() and 0xFF
                (raw - tensorInfo.zeroPoint) * tensorInfo.scale
            }

            DataType.INT8 -> FloatArray(size) { index ->
                val raw = outputBuffer.get(index).toInt()
                (raw - tensorInfo.zeroPoint) * tensorInfo.scale
            }

            else -> FloatArray(size)
        }
    }

    protected fun outputBufferAndShape(): Pair<ByteBuffer, IntArray>? {
        val info = outputInfo ?: return null
        info.first.rewind()
        return info
    }

    fun close() {
        interpreter?.close()
        gpuDelegate?.close()
    }

    private fun maybeCreateDelegate(preference: DelegatePreference): Pair<Delegate, AutoCloseable>? {
        return when (preference) {
            DelegatePreference.CPU -> null
            DelegatePreference.NNAPI -> maybeCreateNnApiDelegate()
            DelegatePreference.GPU -> maybeCreateGpuDelegate()
            DelegatePreference.AUTO -> maybeCreateNnApiDelegate() ?: maybeCreateGpuDelegate()
        }
    }

    private fun maybeCreateGpuDelegate(): Pair<Delegate, AutoCloseable>? {

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

    private fun maybeCreateNnApiDelegate(): Pair<Delegate, AutoCloseable>? {
        return runCatching {
            val optionsClass = Class.forName("org.tensorflow.lite.nnapi.NnApiDelegate\$Options")
            val options = optionsClass.getDeclaredConstructor().newInstance().apply {
                optionsClass.getMethod("setUseNnapiCpu", Boolean::class.javaPrimitiveType).invoke(this, false)
                optionsClass.getMethod("setAllowFp16", Boolean::class.javaPrimitiveType).invoke(this, true)
            }
            val delegateClass = Class.forName("org.tensorflow.lite.nnapi.NnApiDelegate")
            val delegate = delegateClass.getConstructor(optionsClass).newInstance(options)
            @Suppress("UNCHECKED_CAST")
            (delegate as Delegate) to (delegate as AutoCloseable)
        }.getOrNull()
    }

    private fun readResizedPixels(bitmap: Bitmap): IntArray {
        val resized = ensureInputBitmap()
        val canvas = ensureInputCanvas(resized)
        canvas.drawBitmap(bitmap, null, resizeDstRect, resizePaint)
        resized.getPixels(inputPixels, 0, inputSpec.width, 0, 0, inputSpec.width, inputSpec.height)
        return inputPixels
    }

    private fun ensureInputBitmap(): Bitmap {
        val current = inputBitmap
        if (current != null) {
            return current
        }
        return Bitmap.createBitmap(inputSpec.width, inputSpec.height, Bitmap.Config.ARGB_8888).also {
            inputBitmap = it
        }
    }

    private fun ensureInputCanvas(bitmap: Bitmap): Canvas {
        val current = inputCanvas
        if (current != null) {
            current.setBitmap(bitmap)
            return current
        }
        return Canvas(bitmap).also { inputCanvas = it }
    }

    private fun ensureInputBuffer(normalized: Boolean): ByteBuffer {
        val existing = if (normalized) normalizedInputBuffer else rgbInputBuffer
        val requiredBytes = inputTensorInfo?.numBytes ?: (inputSpec.width * inputSpec.height * 3 * 4)
        if (existing != null && existing.capacity() == requiredBytes) {
            return existing
        }
        return ByteBuffer.allocateDirect(requiredBytes).apply {
            order(ByteOrder.nativeOrder())
        }.also { buffer ->
            if (normalized) {
                normalizedInputBuffer = buffer
            } else {
                rgbInputBuffer = buffer
            }
        }
    }

    private fun resolveRgbInputValueScale(): Float {
        val metadataRange = metadata?.inputRange
        val metadataMax = metadataRange?.getOrNull(1)
        if (metadataMax != null && metadataMax > 1.5f) {
            return 1f
        }

        val tensorInfo = inputTensorInfo
        if (tensorInfo != null && tensorInfo.dataType != DataType.FLOAT32 && tensorInfo.scale >= 1f) {
            return 1f
        }
        return 255f
    }
}

private data class TensorInfo(
    val shape: IntArray,
    val dataType: DataType,
    val scale: Float,
    val zeroPoint: Int,
    val numBytes: Int
)

private fun org.tensorflow.lite.Tensor.toTensorInfo(): TensorInfo {
    val quantization = quantizationParams()
    return TensorInfo(
        shape = shape(),
        dataType = dataType(),
        scale = quantization.scale.takeUnless { it == 0f } ?: 1f,
        zeroPoint = quantization.zeroPoint,
        numBytes = numBytes()
    )
}

private fun ByteBuffer.putTensorValue(value: Float, tensorInfo: TensorInfo?) {
    when (tensorInfo?.dataType ?: DataType.FLOAT32) {
        DataType.FLOAT32 -> putFloat(value)
        DataType.UINT8 -> {
            val info = tensorInfo ?: run {
                putFloat(value)
                return
            }
            val quantized = (value / info.scale + info.zeroPoint)
                .toInt()
                .coerceIn(0, 255)
            put(quantized.toByte())
        }

        DataType.INT8 -> {
            val info = tensorInfo ?: run {
                putFloat(value)
                return
            }
            val quantized = (value / info.scale + info.zeroPoint)
                .toInt()
                .coerceIn(-128, 127)
            put(quantized.toByte())
        }

        else -> putFloat(value)
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
