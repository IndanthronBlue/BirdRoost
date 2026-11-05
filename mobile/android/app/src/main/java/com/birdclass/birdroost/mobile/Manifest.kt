package com.birdclass.birdroost.mobile

import org.json.JSONObject

data class PhotoItem(
    val photoId: String,
    val originalKey: String,
    val sha256: String,
    val thumbnailKey: String,
    val speciesCn: String,
    val speciesLatin: String,
    val country: String,
    val region: String,
    val location: String,
    val time: String,
    val groupId: String,
    val special: String,
    val width: Int,
    val height: Int,
)

data class LibraryManifest(
    val revision: Int,
    val photos: List<PhotoItem>,
    val updatedAt: String,
)

fun parseManifest(text: String): LibraryManifest {
    val root = JSONObject(text)
    if (root.optInt("schema_version", 0) != 2) {
        throw IllegalArgumentException("manifest schema 版本不支持：${root.optInt("schema_version", 0)}")
    }
    val groups = mutableMapOf<String, JSONObject>()
    val groupArray = root.optJSONArray("groups") ?: throw IllegalArgumentException("manifest 缺少 groups")
    for (index in 0 until groupArray.length()) {
        val group = groupArray.optJSONObject(index) ?: continue
        groups[group.optString("group_id")] = group
    }
    val firstCopy = mutableMapOf<String, JSONObject>()
    val copies = root.optJSONArray("copies") ?: throw IllegalArgumentException("manifest 缺少 copies")
    for (index in 0 until copies.length()) {
        val copy = copies.optJSONObject(index) ?: continue
        val photoId = copy.optString("photo_id")
        if (photoId.isNotBlank() && !firstCopy.containsKey(photoId)) firstCopy[photoId] = copy
    }
    val photos = mutableListOf<PhotoItem>()
    val photoArray = root.optJSONArray("photos") ?: throw IllegalArgumentException("manifest 缺少 photos")
    for (index in 0 until photoArray.length()) {
        val photo = photoArray.optJSONObject(index) ?: continue
        val photoId = photo.optString("photo_id")
        val copy = firstCopy[photoId] ?: continue
        val group = groups[copy.optString("group_id")] ?: JSONObject()
        val observation = group.optJSONObject("observation") ?: JSONObject()
        val variants = photo.optJSONArray("variants")
        var thumb = photo.optString("original_object_key")
        if (variants != null) {
            for (variantIndex in 0 until variants.length()) {
                val variant = variants.optJSONObject(variantIndex) ?: continue
                if (variant.optString("kind") == "thumb_256") {
                    thumb = variant.optString("object_key", thumb)
                    break
                }
                if (thumb == photo.optString("original_object_key") && variant.optString("kind") == "thumb_512") {
                    thumb = variant.optString("object_key", thumb)
                }
            }
        }
        photos += PhotoItem(
            photoId = photoId,
            originalKey = photo.optString("original_object_key"),
            sha256 = photo.optString("sha256"),
            thumbnailKey = thumb,
            speciesCn = copy.optString("species_cn").ifBlank { "未分类" },
            speciesLatin = copy.optString("species_latin"),
            country = observation.optString("country"),
            region = observation.optString("region"),
            location = observation.optString("location"),
            time = observation.optString("time"),
            groupId = copy.optString("group_id"),
            special = copy.optString("special"),
            width = photo.optInt("width", 0),
            height = photo.optInt("height", 0),
        )
    }
    photos.sortBy { it.speciesCn }
    return LibraryManifest(
        revision = root.optInt("revision", 0),
        photos = photos,
        updatedAt = root.optString("updated_at"),
    )
}
