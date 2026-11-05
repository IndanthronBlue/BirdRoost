package com.birdclass.birdroost.mobile

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            BirdRoostTheme {
                val vm: MainViewModel = viewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                if (state.config == null || state.editingConfig) {
                    ConfigScreen(state = state, onSave = vm::saveConfig, onCancel = vm::cancelEdit)
                } else {
                    LibraryScreen(state = state, vm = vm, onReload = vm::load)
                }
            }
        }
    }
}

@Composable
private fun BirdRoostTheme(content: @Composable () -> Unit) {
    val dark = androidx.compose.foundation.isSystemInDarkTheme()
    val colors = if (dark) darkColorScheme(
        primary = Color(0xFF83D5B0),
        background = Color(0xFF101512),
        surface = Color(0xFF18201B),
    ) else lightColorScheme(
        primary = Color(0xFF1F6B4F),
        background = Color(0xFFF4F1E8),
        surface = Color(0xFFFFFBF2),
    )
    MaterialTheme(colorScheme = colors, content = content)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ConfigScreen(state: UiState, onSave: (CosSettings) -> Unit, onCancel: () -> Unit) {
    if (state.config != null) {
        BackHandler(onBack = onCancel)
    }
    var bucket by remember { mutableStateOf(state.config?.bucket.orEmpty()) }
    var region by remember { mutableStateOf(state.config?.region ?: "ap-shanghai") }
    var prefix by remember { mutableStateOf(state.config?.prefix ?: "zjq") }
    var endpoint by remember { mutableStateOf(state.config?.endpoint.orEmpty()) }
    var secretId by remember { mutableStateOf(state.config?.secretId.orEmpty()) }
    var secretKey by remember { mutableStateOf(state.config?.secretKey.orEmpty()) }
    Surface(Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("羽栖 BirdRoost", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("手机只读图库", style = MaterialTheme.typography.titleMedium)
            Text(
                "填写只读 COS 子账号。SecretKey 只保存在 Android Keystore，不会上传到第三方。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(bucket, { bucket = it }, label = { Text("桶名（含 APPID）") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(region, { region = it }, label = { Text("地域") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(prefix, { prefix = it }, label = { Text("用户前缀") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Endpoint（可选）") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(secretId, { secretId = it }, label = { Text("SecretId") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(
                secretKey, { secretKey = it }, label = { Text("SecretKey") },
                modifier = Modifier.fillMaxWidth(), singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            )
            if (state.error != null) Text(state.error, color = MaterialTheme.colorScheme.error)
            if (state.config != null) {
                TextButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text("取消") }
            }
            Button(
                onClick = { onSave(CosSettings(bucket, region, endpoint, prefix, secretId, secretKey)) },
                enabled = !state.loading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.loading) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else Text("保存并读取云端图库")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LibraryScreen(state: UiState, vm: MainViewModel, onReload: () -> Unit) {
    val items = state.manifest?.photos.orEmpty()
    var query by remember { mutableStateOf("") }
    var species by remember { mutableStateOf("全部") }
    var treeFilter by remember { mutableStateOf<TaxonNode?>(null) }
    var selected by remember { mutableStateOf<PhotoItem?>(null) }
    val speciesCounts = remember(items) {
        items.groupingBy { it.speciesCn }.eachCount().toList().sortedByDescending { it.second }
    }
    val searchOptions = remember(items, speciesCounts) {
        buildList {
            speciesCounts.filter { it.first != "未收录" && it.first.isNotBlank() }.forEach { (name, count) ->
                add(SearchOption(name, "物种 · $count", name))
            }
            items.map { it.location.trim() }.filter { it.isNotBlank() }.distinct().forEach {
                add(SearchOption(it, "地点", it))
            }
            items.map { it.time.trim() }.filter { it.isNotBlank() }.distinct().forEach {
                add(SearchOption(it, "时间", it))
            }
            items.map { it.speciesLatin.trim() }.filter { it.isNotBlank() }.distinct().forEach {
                add(SearchOption(it, "学名", it))
            }
            items.map { it.country.trim() }.filter { it.isNotBlank() }.distinct().forEach {
                add(SearchOption(it, "国家/地区", it))
            }
        }.distinctBy { it.value }
    }
    val filtered = remember(items, query, species, treeFilter) {
        items.filter { item ->
            (treeFilter == null || treeFilter!!.species.contains(item.speciesCn)) &&
                (species == "全部" || item.speciesCn == species) &&
                (query.isBlank() || listOf(item.speciesCn, item.speciesLatin, item.location, item.time, item.country)
                    .any { it.contains(query, ignoreCase = true) })
        }
    }
    var expandedIds by remember(state.tree) {
        mutableStateOf(state.tree.map { it.id }.toSet())
    }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                Text("分类树", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(20.dp))
                LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        TreeRow(
                            label = "全部图库",
                            count = items.size,
                            depth = 0,
                            expanded = false,
                            hasChildren = false,
                            onToggle = {},
                            onSelect = {
                                treeFilter = null
                                scope.launch { drawerState.close() }
                            },
                        )
                    }
                    items(state.tree, key = { it.id }) { node ->
                        TreeNode(
                            node = node,
                            depth = 0,
                            expandedIds = expandedIds,
                            onToggle = { id ->
                                expandedIds = if (id in expandedIds) expandedIds - id else expandedIds + id
                            },
                            onSelect = {
                                treeFilter = it
                                species = "全部"
                                scope.launch { drawerState.close() }
                            },
                        )
                    }
                }
            }
        },
    ) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("羽栖 BirdRoost") },
                navigationIcon = {
                    IconButton(onClick = { scope.launch { drawerState.open() } }) {
                        Icon(Icons.Default.Menu, contentDescription = "分类树")
                    }
                },
                actions = {
                    IconButton(onClick = onReload) { Icon(Icons.Default.Refresh, contentDescription = "刷新") }
                    IconButton(onClick = { vm.editConfig() }) { Icon(Icons.Default.Settings, contentDescription = "配置") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (state.error != null) Text(state.error, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
            SearchField(
                query = query,
                options = searchOptions,
                onQueryChange = { query = it },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )
            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item {
                    FilterChip(selected = species == "全部" && treeFilter == null, onClick = { species = "全部"; treeFilter = null }, label = { Text("全部 ${items.size}") })
                }
                items(speciesCounts.take(30)) { (name, count) ->
                    FilterChip(selected = species == name, onClick = { species = name; treeFilter = null }, label = { Text("$name $count") })
                }
            }
            treeFilter?.let { active ->
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "分类：${active.label}",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { treeFilter = null }) { Text("清除") }
                }
            }
            Text(
                "revision ${state.manifest?.revision ?: "-"} · ${filtered.size} 张",
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (filtered.isEmpty() && !state.loading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("没有匹配的照片", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(2),
                    contentPadding = PaddingValues(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(filtered, key = { it.photoId }) { item ->
                        PhotoCard(item, vm.thumbnailUrl(item)) { selected = item }
                    }
                }
            }
        }
    }
    }
    selected?.let { item ->
        PhotoDialog(item, vm.originalUrl(item), onClose = { selected = null })
    }
}

private data class SearchOption(val label: String, val type: String, val value: String)

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SearchField(
    query: String,
    options: List<SearchOption>,
    onQueryChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    var focused by remember { mutableStateOf(false) }
    val imeVisible = WindowInsets.isImeVisible
    val focusManager = LocalFocusManager.current
    LaunchedEffect(imeVisible) {
        if (imeVisible) expanded = true
    }
    val matches = remember(query, options) {
        if (query.isBlank()) options.take(10)
        else options.filter { it.label.contains(query, ignoreCase = true) }
            .sortedBy { if (it.label.startsWith(query, ignoreCase = true)) 0 else 1 }
            .take(12)
    }
    Column(modifier) {
        OutlinedTextField(
            value = query,
            onValueChange = {
                onQueryChange(it)
                expanded = true
            },
            label = { Text("搜索物种、地点、时间") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().onFocusChanged {
                focused = it.isFocused
                expanded = it.isFocused
            },
            trailingIcon = {
                if (query.isNotEmpty()) {
                    IconButton(onClick = {
                        onQueryChange("")
                        expanded = true
                    }) { Icon(Icons.Default.Clear, contentDescription = "清空搜索") }
                }
            },
        )
        if (expanded && focused && imeVisible && matches.isNotEmpty()) {
            Surface(
                modifier = Modifier.fillMaxWidth().heightIn(max = 300.dp),
                shape = RoundedCornerShape(12.dp),
                tonalElevation = 3.dp,
                shadowElevation = 4.dp,
            ) {
                LazyColumn {
                    items(matches, key = { "${it.type}:${it.value}" }) { option ->
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable {
                                    onQueryChange(option.value)
                                    expanded = false
                                    focusManager.clearFocus()
                                }
                                .padding(horizontal = 16.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                option.label,
                                modifier = Modifier.weight(1f),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                option.type,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.35f))
                    }
                }
            }
        }
    }
}

@Composable
private fun TreeNode(
    node: TaxonNode,
    depth: Int,
    expandedIds: Set<String>,
    onToggle: (String) -> Unit,
    onSelect: (TaxonNode) -> Unit,
) {
    val expanded = node.id in expandedIds
    TreeRow(
        label = node.label,
        count = node.count,
        depth = depth,
        expanded = expanded,
        hasChildren = node.children.isNotEmpty(),
        onToggle = { onToggle(node.id) },
        onSelect = { onSelect(node) },
    )
    if (expanded) {
        node.children.forEach { child ->
            TreeNode(child, depth + 1, expandedIds, onToggle, onSelect)
        }
    }
}

@Composable
private fun TreeRow(
    label: String,
    count: Int,
    depth: Int,
    expanded: Boolean,
    hasChildren: Boolean,
    onToggle: () -> Unit,
    onSelect: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().padding(start = (10 + depth * 14).dp, end = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (hasChildren) {
            IconButton(onClick = onToggle, modifier = Modifier.size(34.dp)) {
                Icon(
                    if (expanded) Icons.Default.KeyboardArrowDown else Icons.Default.KeyboardArrowRight,
                    contentDescription = if (expanded) "收起" else "展开",
                )
            }
        } else {
            Spacer(Modifier.width(34.dp))
        }
        Text(
            label,
            modifier = Modifier.weight(1f).clickable(onClick = onSelect).padding(vertical = 11.dp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            "$count",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PhotoCard(item: PhotoItem, url: String?, onClick: () -> Unit) {
    Column(
        Modifier.clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surface)
            .clickable(onClick = onClick)
            .padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        AsyncImage(
            model = url,
            contentDescription = item.speciesCn,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(10.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            onError = { Log.e("BirdRoost", "thumbnail failed: ${item.thumbnailKey}", it.result.throwable) },
        )
        Text(item.speciesCn, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.SemiBold)
        Text(
            listOf(item.location, item.time).filter { it.isNotBlank() }.joinToString(" · "),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PhotoDialog(item: PhotoItem, url: String?, onClose: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var downloading by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(item.speciesCn) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                AsyncImage(
                    model = url,
                    contentDescription = item.speciesCn,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().heightIn(max = 420.dp).clip(RoundedCornerShape(10.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                )
                Text(listOf(item.speciesLatin, item.country, item.region, item.location, item.time)
                    .filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                OutlinedButton(
                    onClick = {
                        val original = url ?: return@OutlinedButton
                        scope.launch {
                            downloading = true
                            val ok = downloadToGallery(context, original, item)
                            downloading = false
                            Toast.makeText(
                                context,
                                if (ok) "已保存到相册/BirdRoost" else "下载失败",
                                Toast.LENGTH_SHORT,
                            ).show()
                        }
                    },
                    enabled = !downloading,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (downloading) "正在下载…" else "下载原图到相册") }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text("关闭") } },
    )
}

private suspend fun downloadToGallery(context: Context, url: String, item: PhotoItem): Boolean =
    withContext(Dispatchers.IO) {
        if (Build.VERSION.SDK_INT < 29) return@withContext false
        val extension = item.originalKey.substringAfterLast('.', "jpg")
        val mime = if (extension == "png") "image/png" else "image/jpeg"
        val name = "BirdRoost_${item.photoId.take(12)}.$extension"
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, name)
            put(MediaStore.Images.Media.MIME_TYPE, mime)
            put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/BirdRoost")
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
        val collection = MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        val uri = resolver.insert(collection, values) ?: return@withContext false
        try {
            val request = Request.Builder().url(url).get().build()
            OkHttpClient().newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext false
                val body = response.body ?: return@withContext false
                resolver.openOutputStream(uri)?.use { output ->
                    body.byteStream().copyTo(output)
                } ?: return@withContext false
            }
            val done = ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
            true
        } catch (exc: Exception) {
            resolver.delete(uri, null, null)
            false
        }
    }
