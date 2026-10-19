module.exports = function (api) {
  api.cache(true);
  return {
    // babel-preset-expo includes the expo-router transform for SDK 50+.
    presets: ["babel-preset-expo"],
    env: {
      // Strip console.* calls from production bundles only. Dev/test builds
      // keep console output intact for debugging.
      production: {
        plugins: ["transform-remove-console"],
      },
    },
  };
};
