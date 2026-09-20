import Foundation

enum ProductConfiguration {
    static let cloudURL: String = {
        guard let url = Bundle.main.url(forResource: "product", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let config = try? JSONDecoder().decode(Configuration.self, from: data),
              URL(string: config.cloudURL)?.scheme == "https" else {
            preconditionFailure("Missing or invalid packaged product.json")
        }
        return config.cloudURL
    }()
    private struct Configuration: Decodable { let cloudURL: String }
}
