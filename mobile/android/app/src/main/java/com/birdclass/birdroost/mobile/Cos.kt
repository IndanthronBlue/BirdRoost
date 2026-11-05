package com.birdclass.birdroost.mobile

import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

data class CosSettings(
    val bucket: String,
    val region: String,
    val endpoint: String,
    val prefix: String,
    val secretId: String,
    val secretKey: String,
)

private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

private fun sha1(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-1").digest(bytes)

private fun hmacSha1(key: ByteArray, data: ByteArray): ByteArray {
    val mac = Mac.getInstance("HmacSHA1")
    mac.init(SecretKeySpec(key, "HmacSHA1"))
    return mac.doFinal(data)
}

fun normalizePrefix(value: String): String {
    val cleaned = value.trim().trim('/').replace(Regex("[^\\w.-]+"), "_").take(80).trim('.', '_', '-')
    return cleaned.ifBlank { "default" }
}

class CosClient(val settings: CosSettings) {
    private val http = OkHttpClient.Builder().build()
    val host: String = run {
        val custom = settings.endpoint.trim().removePrefix("https://").removePrefix("http://")
        if (custom.isNotBlank()) custom.trimEnd('/')
        else "${settings.bucket}.cos.${settings.region}.myqcloud.com"
    }

    private fun encodeKey(key: String): String = key.split("/").joinToString("/") {
        URLEncoder.encode(it, Charsets.UTF_8.name()).replace("+", "%20")
    }

    fun signedUrl(key: String, expiresSeconds: Long = 3600): String {
        val path = "/" + encodeKey(key.trimStart('/'))
        val now = System.currentTimeMillis() / 1000
        val end = now + expiresSeconds
        val signTime = "$now;$end"
        val keyTime = "$now;$end"
        val signKey = hex(hmacSha1(settings.secretKey.toByteArray(), keyTime.toByteArray()))
        val httpString = "get\n$path\n\nhost=$host\n"
        val stringToSign = "sha1\n$signTime\n${hex(sha1(httpString.toByteArray()))}\n"
        val signature = hex(hmacSha1(signKey.toByteArray(), stringToSign.toByteArray()))
        val encodedSignTime = URLEncoder.encode(signTime, "UTF-8")
        val query = "q-sign-algorithm=sha1&q-ak=${URLEncoder.encode(settings.secretId, "UTF-8")}" +
            "&q-sign-time=$encodedSignTime&q-key-time=$encodedSignTime" +
            "&q-header-list=host&q-url-param-list=&q-signature=$signature"
        return "https://$host$path?$query"
    }

    fun manifestKey(): String = "users/${normalizePrefix(settings.prefix)}/manifest.json"

    fun getText(key: String): String {
        val request = Request.Builder().url(signedUrl(key)).get().build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("COS ${response.code}: ${response.message}")
            }
            return response.body?.string() ?: throw IllegalStateException("COS 返回为空")
        }
    }
}
