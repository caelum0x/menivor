// No-op AsyncStorage stand-in used only by the Node vitest runner, which cannot
// load the native module. Production/native bundles resolve the real package;
// the product unit tests inject an in-memory storage backend and never touch
// this default. See vitest.product.config.ts.
const noop = {
  getItem: () => Promise.resolve(null),
  setItem: () => Promise.resolve(),
  removeItem: () => Promise.resolve(),
};
module.exports = noop;
module.exports.default = noop;
