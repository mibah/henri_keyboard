plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "de.henri.keyboard"
    compileSdk = 35

    defaultConfig {
        applicationId = "de.henri.keyboard"
        minSdk = 21
        targetSdk = 35
        versionCode = 6
        versionName = "0.5"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}
