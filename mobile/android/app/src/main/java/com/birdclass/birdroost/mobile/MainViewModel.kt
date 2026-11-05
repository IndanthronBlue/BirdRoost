package com.birdclass.birdroost.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class UiState(
    val config: CosSettings? = null,
    val manifest: LibraryManifest? = null,
    val tree: List<TaxonNode> = emptyList(),
    val loading: Boolean = false,
    val error: String? = null,
    val editingConfig: Boolean = false,
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val store = ConfigStore(application)
    private var taxonomy: Taxonomy? = null
    private val _state = MutableStateFlow(UiState(config = store.load()))
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        if (_state.value.config != null) load()
    }

    fun saveConfig(config: CosSettings) {
        val normalized = config.copy(
            bucket = config.bucket.trim(),
            region = config.region.trim().ifBlank { "ap-shanghai" },
            endpoint = config.endpoint.trim(),
            prefix = normalizePrefix(config.prefix),
            secretId = config.secretId.trim(),
            secretKey = config.secretKey.trim(),
        )
        if (normalized.bucket.isBlank() || normalized.secretId.isBlank() || normalized.secretKey.isBlank()) {
            _state.value = _state.value.copy(error = "桶名、SecretId、SecretKey 不能为空")
            return
        }
        store.save(normalized)
        _state.value = _state.value.copy(config = normalized, error = null, editingConfig = false)
        load()
    }

    fun editConfig() {
        _state.value = _state.value.copy(editingConfig = true, error = null)
    }

    fun cancelEdit() {
        if (_state.value.config != null) {
            _state.value = _state.value.copy(editingConfig = false, error = null)
        }
    }

    fun load() {
        val config = _state.value.config ?: return
        _state.value = _state.value.copy(loading = true, error = null)
        viewModelScope.launch {
            try {
                val text = withContext(Dispatchers.IO) {
                    CosClient(config).getText(CosClient(config).manifestKey())
                }
                val manifest = withContext(Dispatchers.Default) { parseManifest(text) }
                val taxonomy = taxonomy ?: withContext(Dispatchers.IO) { Taxonomy.load(getApplication()) }
                    .also { taxonomy = it }
                val tree = withContext(Dispatchers.Default) { buildTaxonomyTree(manifest.photos, taxonomy) }
                _state.value = _state.value.copy(manifest = manifest, tree = tree, loading = false)
            } catch (exc: Exception) {
                _state.value = _state.value.copy(
                    loading = false,
                    error = exc.message ?: exc.javaClass.simpleName,
                )
            }
        }
    }

    private fun objectKey(config: CosSettings, relative: String): String =
        "users/${normalizePrefix(config.prefix)}/${relative.trimStart('/')}"

    fun thumbnailUrl(item: PhotoItem): String? {
        val config = _state.value.config ?: return null
        return CosClient(config).signedUrl(objectKey(config, item.thumbnailKey))
    }

    fun originalUrl(item: PhotoItem): String? {
        val config = _state.value.config ?: return null
        return CosClient(config).signedUrl(objectKey(config, item.originalKey))
    }
}
