/**
 * Sign Android release builds with this app's Play upload key.
 *
 * `expo prebuild` regenerates android/ from the template, whose release build
 * type is signed with the debug key. Play rejects debug-signed bundles, so the
 * release signing is injected here instead of hand-editing build.gradle.
 *
 * No secret lives in the repo. The plugin points Gradle at a per-app
 * properties file outside the repo (mode 600):
 *
 *   ~/.config/products-keys/<keyDir>/upload.properties
 *     storeFile=/absolute/path/to/upload.jks
 *     storePassword=...
 *     keyAlias=...
 *     keyPassword=...
 *
 * Override the path with the ANDROID_UPLOAD_PROPERTIES env var (CI).
 * If the file is missing the release build falls back to the debug key, so a
 * checkout without the key still builds locally; that bundle cannot be
 * uploaded to Play.
 *
 * Usage in app.json: ["./plugins/withAndroidUploadSigning", { "keyDir": "bump-app" }]
 */
const { withAppBuildGradle } = require('expo/config-plugins')

const MARKER = 'products-keys-upload-signing'

function loaderBlock(keyDir) {
  return `
// ${MARKER}: per-app upload key, kept outside the repo.
def uploadPropsPath = System.getenv("ANDROID_UPLOAD_PROPERTIES") ?: "\${System.getProperty('user.home')}/.config/products-keys/${keyDir}/upload.properties"
def uploadPropsFile = new File(uploadPropsPath)
def uploadProps = new Properties()
if (uploadPropsFile.exists()) {
    uploadPropsFile.withInputStream { uploadProps.load(it) }
}
def hasUploadKey = uploadProps.getProperty('storeFile') != null
`
}

const SIGNING_CONFIG = `
        upload {
            if (hasUploadKey) {
                storeFile file(uploadProps.getProperty('storeFile'))
                storePassword uploadProps.getProperty('storePassword')
                keyAlias uploadProps.getProperty('keyAlias')
                keyPassword uploadProps.getProperty('keyPassword')
            }
        }
`

function applySigning(contents, keyDir) {
  if (contents.includes(MARKER)) return contents

  const withLoader = contents.replace(/^android\s*\{/m, (m) => `${loaderBlock(keyDir)}\n${m}`)
  if (withLoader === contents) {
    throw new Error('withAndroidUploadSigning: could not find the android { } block')
  }

  const withConfig = withLoader.replace(/(signingConfigs\s*\{)/, `$1${SIGNING_CONFIG}`)
  if (withConfig === withLoader) {
    throw new Error('withAndroidUploadSigning: could not find the signingConfigs block')
  }

  const withBuildType = withConfig.replace(
    /(buildTypes\s*\{[\s\S]*?release\s*\{(?:\s*\/\/[^\n]*\n)*)\s*signingConfig signingConfigs\.debug/,
    `$1            signingConfig hasUploadKey ? signingConfigs.upload : signingConfigs.debug`,
  )
  if (withBuildType === withConfig) {
    throw new Error('withAndroidUploadSigning: could not repoint the release build type')
  }
  return withBuildType
}

function withAndroidUploadSigning(config, props = {}) {
  const keyDir = props.keyDir
  if (!keyDir || !/^[a-z0-9-]+$/.test(keyDir)) {
    throw new Error('withAndroidUploadSigning: pass a keyDir like "bump-app"')
  }
  return withAppBuildGradle(config, (cfg) => {
    if (cfg.modResults.language !== 'groovy') {
      throw new Error('withAndroidUploadSigning: expected a Groovy build.gradle')
    }
    cfg.modResults.contents = applySigning(cfg.modResults.contents, keyDir)
    return cfg
  })
}

module.exports = withAndroidUploadSigning
module.exports.applySigning = applySigning
