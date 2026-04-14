import CoreML
import Foundation

struct ModelMetadata: Decodable {
    let name: String?
    let exportedModel: String?
    let format: String?
    let inputShape: [Int]?
    let outputShape: [Int]?
    let inputLayout: String?
    let inputRange: [Float]?
    let normalizeMean: [Float]?
    let normalizeStd: [Float]?
    let trackedClassIds: [Int]?
    let preferredDelegate: String?

    enum CodingKeys: String, CodingKey {
        case name
        case exportedModel = "exported_model"
        case format
        case inputShape = "input_shape"
        case outputShape = "output_shape"
        case inputLayout = "input_layout"
        case inputRange = "input_range"
        case normalizeMean = "normalize_mean"
        case normalizeStd = "normalize_std"
        case trackedClassIds = "tracked_class_ids"
        case preferredDelegate = "preferred_delegate"
    }
}

struct ModelAssetLocator {
    private static let subdirectories: [String?] = [
        nil,
        "Models",
        "Resources",
        "Resources/Models",
    ]

    static func modelURL(baseName: String) throws -> URL {
        let bundle = Bundle.main
        for subdirectory in subdirectories {
            if let compiled = bundle.url(forResource: baseName, withExtension: "mlmodelc", subdirectory: subdirectory) {
                return compiled
            }
            if let package = bundle.url(forResource: baseName, withExtension: "mlpackage", subdirectory: subdirectory) {
                return try MLModel.compileModel(at: package)
            }
        }
        throw AnalysisErrors.modelsNotReady
    }

    static func metadata(baseName: String) throws -> ModelMetadata {
        for subdirectory in subdirectories {
            if let url = Bundle.main.url(forResource: baseName, withExtension: "json", subdirectory: subdirectory) {
                let data = try Data(contentsOf: url)
                return try JSONDecoder().decode(ModelMetadata.self, from: data)
            }
        }
        throw AnalysisErrors.modelsNotReady
    }
}
