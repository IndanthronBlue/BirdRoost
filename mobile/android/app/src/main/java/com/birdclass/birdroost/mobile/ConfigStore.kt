package com.birdclass.birdroost.mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class ConfigStore(context: Context) {
    private val prefs = context.getSharedPreferences("birdroost_secure", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias(ALIAS)) {
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            generator.init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build(),
            )
            generator.generateKey()
        }
        return (store.getEntry(ALIAS, null) as KeyStore.SecretKeyEntry).secretKey
    }

    fun save(settings: CosSettings) {
        val plain = JSONObject().apply {
            put("bucket", settings.bucket)
            put("region", settings.region)
            put("endpoint", settings.endpoint)
            put("prefix", settings.prefix)
            put("secretId", settings.secretId)
            put("secretKey", settings.secretKey)
        }.toString()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(plain.toByteArray())
        prefs.edit()
            .putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("data", Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .apply()
    }

    fun load(): CosSettings? {
        val ivText = prefs.getString("iv", null) ?: return null
        val dataText = prefs.getString("data", null) ?: return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.decode(ivText, Base64.NO_WRAP)),
            )
            val plain = String(cipher.doFinal(Base64.decode(dataText, Base64.NO_WRAP)))
            val json = JSONObject(plain)
            CosSettings(
                bucket = json.optString("bucket"),
                region = json.optString("region", "ap-shanghai"),
                endpoint = json.optString("endpoint"),
                prefix = json.optString("prefix", "default"),
                secretId = json.optString("secretId"),
                secretKey = json.optString("secretKey"),
            )
        } catch (_: Exception) {
            null
        }
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val ALIAS = "birdroost_cos_config"
    }
}
