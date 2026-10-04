plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.brb.pdf"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.brb.pdf"
        minSdk = 26            // Android 8.0 and newer
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        ndk {
            // phones (arm64 / older arm) and the Android Studio emulator (x86_64)
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    androidResources {
        // OCR language files are large and already compressed; store them as they are
        noCompress += listOf("traineddata", "ttf")
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }
}

dependencies {
    // MuPDF: the same PDF engine the Windows version uses (AGPL-3.0)
    implementation("com.artifex.mupdf:fitz:1.28.5")
    // Tesseract OCR for Android: offline English, Bengali, Hindi (Apache-2.0)
    implementation("cz.adaptech.tesseract4android:tesseract4android:4.9.0")
}
