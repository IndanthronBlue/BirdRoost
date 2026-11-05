package com.birdclass.birdroost.mobile

import android.content.Context

data class TaxonomyPath(
    val kingdom: String,
    val phylum: String,
    val className: String,
    val order: String,
    val family: String,
    val genus: String,
    val species: String,
)

data class TaxonNode(
    val id: String,
    val label: String,
    val count: Int,
    val species: Set<String>,
    val children: List<TaxonNode>,
)

class Taxonomy private constructor(private val paths: Map<String, TaxonomyPath>) {
    fun pathFor(speciesCn: String): TaxonomyPath? = paths[speciesCn.trim()]

    companion object {
        fun load(context: Context): Taxonomy {
            val result = mutableMapOf<String, TaxonomyPath>()
            val scientificIndex = mutableMapOf<String, TaxonomyPath>()
            context.assets.open("taxonomy/ioc_15_2_birds.csv").bufferedReader().useLines { lines ->
                val iterator = lines.iterator()
                if (!iterator.hasNext()) return@useLines
                val header = parseCsvLine(iterator.next())
                fun index(name: String): Int = header.indexOf(name)
                val nameIndex = index("name_zh")
                val traditionalIndex = index("name_zh_trad")
                val kingdomIndex = index("kingdom")
                val phylumIndex = index("phylum")
                val classIndex = index("class")
                val orderIndex = index("order")
                val orderZhIndex = index("order_zh")
                val familyIndex = index("family")
                val familyZhIndex = index("family_zh")
                val genusIndex = index("genus")
                val genusZhIndex = index("genus_zh")
                while (iterator.hasNext()) {
                    val row = parseCsvLine(iterator.next())
                    fun value(position: Int): String = row.getOrNull(position)?.trim().orEmpty()
                    val name = value(nameIndex)
                    if (name.isBlank()) continue
                    val path = TaxonomyPath(
                        kingdom = value(kingdomIndex).ifBlank { "动物界" },
                        phylum = value(phylumIndex).ifBlank { "脊索动物门" },
                        className = value(classIndex).ifBlank { "鸟纲" },
                        order = value(orderZhIndex).ifBlank { value(orderIndex).ifBlank { "未分类目" } },
                        family = value(familyZhIndex).ifBlank { value(familyIndex).ifBlank { "未分类科" } },
                        genus = value(genusZhIndex).ifBlank { value(genusIndex).ifBlank { "未分类属" } },
                        species = name,
                    )
                    result[name] = path
                    scientificIndex[value(index("scientific_name"))] = path
                    val traditional = value(traditionalIndex)
                    if (traditional.isNotBlank()) result.putIfAbsent(traditional, path)
                }
            }
            try {
                context.assets.open("taxonomy/taxonomy_aliases.csv").bufferedReader().useLines { lines ->
                    val iterator = lines.iterator()
                    if (!iterator.hasNext()) return@useLines
                    val header = parseCsvLine(iterator.next())
                    val aliasIndex = header.indexOf("alias")
                    val scientificNameIndex = header.indexOf("scientific_name")
                    while (iterator.hasNext()) {
                        val row = parseCsvLine(iterator.next())
                        val alias = row.getOrNull(aliasIndex)?.trim().orEmpty()
                        val scientific = row.getOrNull(scientificNameIndex)?.trim().orEmpty()
                        if (alias.isBlank() || scientific.isBlank()) continue
                        val path = scientificIndex[scientific] ?: continue
                        result.putIfAbsent(alias, path)
                    }
                }
            } catch (_: Exception) {
                // Alias data is optional.
            }
            return Taxonomy(result)
        }

        private fun parseCsvLine(line: String): List<String> {
            val values = mutableListOf<String>()
            val current = StringBuilder()
            var quoted = false
            var index = 0
            while (index < line.length) {
                val char = line[index]
                when {
                    char == '"' && quoted && index + 1 < line.length && line[index + 1] == '"' -> {
                        current.append('"')
                        index++
                    }
                    char == '"' -> quoted = !quoted
                    char == ',' && !quoted -> {
                        values.add(current.toString())
                        current.clear()
                    }
                    else -> current.append(char)
                }
                index++
            }
            values.add(current.toString())
            return values
        }
    }
}

fun buildTaxonomyTree(photos: List<PhotoItem>, taxonomy: Taxonomy): List<TaxonNode> {
    val root = MutableNode("", "全部图库")
    for (photo in photos) {
        val species = photo.speciesCn.ifBlank { "未分类" }
        if (photo.special.isNotBlank()) {
            root.add(listOf("特殊照片", photo.special), species)
            continue
        }
        val path = taxonomy.pathFor(species)
        val labels = if (path == null) {
            listOf("未收录", species)
        } else {
            listOf(path.kingdom, path.phylum, path.className, path.order, path.family, path.genus, path.species)
        }
        root.add(labels, species)
    }
    return root.toNodes().children
}

private class MutableNode(val id: String, val label: String) {
    val children = linkedMapOf<String, MutableNode>()
    val speciesSet = linkedSetOf<String>()
    var count = 0

    fun add(labels: List<String>, species: String) {
        count++
        speciesSet.add(species)
        if (labels.isEmpty()) return
        val nextId = if (id.isBlank()) labels.first() else "$id|${labels.first()}"
        val child = children.getOrPut(labels.first()) { MutableNode(nextId, labels.first()) }
        child.add(labels.drop(1), species)
    }

    fun toNodes(): TaxonNode = TaxonNode(
        id = id,
        label = label,
        count = count,
        species = speciesSet,
        children = children.values.map { it.toNodes() },
    )
}
