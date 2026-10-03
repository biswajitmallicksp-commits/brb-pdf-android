plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// CI sets GITHUB_RUN_NUMBER so every published APK installs as an upgrade.
val buildNumber = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull() ?: 1

android {
    namespace = "com.brb.statementanalyzer"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.brb.statementanalyzer"
        minSdk = 26
        targetSdk = 35
        versionCode = buildNumber
        versionName = "2.0.$buildNumber"
    }

    signingConfigs {
        // A fixed key keeps every build's signature identical, so new APKs
        // install over old ones without losing the statement database.
        create("shared") {
            storeFile = file("signing/brb-release.jks")
            storePassword = "brbstatement"
            keyAlias = "brb"
            keyPassword = "brbstatement"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("shared")
        }
        debug {
            signingConfig = signingConfigs.getByName("shared")
        }
    }

    // The whole app is the HTML page in /web; the APK only hosts it in a WebView.
    sourceSets["main"].assets.srcDirs("../web")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.webkit:webkit:1.12.1")
}
