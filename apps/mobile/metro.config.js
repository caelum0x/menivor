// Metro configuration — stock Expo defaults.
//
// The previous web-only resolver shim for `react-native-google-mobile-ads`
// was removed along with the AdMob integration (Menivor ships ad-free).
const { getDefaultConfig } = require('expo/metro-config');

module.exports = getDefaultConfig(__dirname);
