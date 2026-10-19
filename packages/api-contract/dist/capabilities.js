export function canGenerate(capabilities, feature) {
    return capabilities.generation[feature];
}
export function canonicalGenerationRoute(capabilities, feature) {
    return capabilities.canonical_routes[feature];
}
