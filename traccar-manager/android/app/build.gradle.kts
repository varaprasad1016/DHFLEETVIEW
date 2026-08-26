import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("../../environment/key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

fun secret(name: String): String? {
    return keystoreProperties.getProperty(name) ?: System.getenv(name)
}

val releaseStoreFile: File? = secret("STORE_FILE")?.let { file(it) }
    ?: keystoreProperties["storeFile"]?.let { file(it) }
val hasReleaseSigning = secret("KEYSTORE_PASSWORD") != null
    && releaseStoreFile != null
    && releaseStoreFile.exists()

android {
    namespace = "com.dhgroup.fleetview"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "com.dhgroup.fleetview"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                keyAlias = secret("KEY_ALIAS") ?: "dhfleetview"
                keyPassword = secret("KEY_PASSWORD")
                storeFile = releaseStoreFile
                storePassword = secret("KEYSTORE_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
}

flutter {
    source = "../.."
}
