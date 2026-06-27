package com.w49.chatprobe

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.TextView
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

class MainActivity : android.app.Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val tv = TextView(this)
        tv.text = "55Chat 探针\n\n请在系统设置中开启本应用的无障碍服务。\n\n探针 URL: http://127.0.0.1:3910/event"
        tv.setPadding(48, 48, 48, 48)
        setContentView(tv)
        startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }
}

class ProbeAccessibilityService : AccessibilityService() {
    private val executor = Executors.newSingleThreadExecutor()
    private val lastPost = AtomicLong(0)
    private val seen = LinkedHashSet<String>()
    private val seenTs = LinkedHashMap<String, Long>()

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        val pkg = event.packageName?.toString() ?: return
        if (!pkg.startsWith("wuwu.")) return
        val root = rootInActiveWindow ?: return
        val texts = mutableListOf<String>()
        collectTexts(root, texts)
        root.recycle()
        if (texts.isEmpty()) return

        val cmd = texts.lastOrNull { isCommandLike(it) } ?: return
        val normCmd = normalizeCommand(cmd)
        val sender = findSender(texts, cmd) ?: ""
        val sig = "$sender|$normCmd"
        val now = System.currentTimeMillis()
        synchronized(seenTs) {
            val last = seenTs[sig] ?: 0L
            if (now - last < 4000) return
            seenTs[sig] = now
            if (seenTs.size > 200) {
                while (seenTs.size > 150) {
                    val k = seenTs.keys.first()
                    seenTs.remove(k)
                    seen.remove(k)
                }
            }
        }
        synchronized(seen) {
            if (seen.contains(sig)) return
            seen.add(sig)
            if (seen.size > 200) {
                while (seen.size > 150) {
                    seen.remove(seen.first())
                }
            }
        }
        if (now - lastPost.get() < 1500) return
        lastPost.set(now)
        val payload = """{"package":"$pkg","sender":${jsonStr(sender)},"command":${jsonStr(normCmd)},"texts":${jsonArr(texts.takeLast(12))},"ts":$now}"""
        executor.execute { postEvent(payload) }
    }

    override fun onInterrupt() {}

    private fun collectTexts(node: AccessibilityNodeInfo, out: MutableList<String>) {
        val t = node.text?.toString()?.trim().orEmpty()
        if (t.isNotEmpty() && t.length <= 120) out.add(t)
        val d = node.contentDescription?.toString()?.trim().orEmpty()
        if (d.isNotEmpty() && d.length <= 80 && d != t) out.add(d)
        for (i in 0 until node.childCount) {
            val c = node.getChild(i) ?: continue
            collectTexts(c, out)
            c.recycle()
        }
    }

    private fun normalizeCommand(cmd: String): String {
        val t = cmd.trim()
        if (Regex("""^扣?1$""").matches(t)) return "扣1"
        if (t == "查余额" || t == "余额查询") return "扣1"
        return t
    }

    private fun isCommandLike(s: String): Boolean {
        val t = s.trim()
        if (t.isEmpty() || t.length > 80) return false
        if (t in IGNORE) return false
        if (Regex("""^扣?1$""").matches(t)) return true
        if (t.contains("各") && t.contains("/")) return true
        if (t.startsWith("购买") || t.startsWith("上") || t.startsWith("下")) return true
        if (t.startsWith("扣")) return true
        return false
    }

    private fun findSender(texts: List<String>, cmd: String): String? {
        val idx = texts.indexOfLast { it.trim() == cmd.trim() }
        if (idx <= 0) return null
        for (j in idx - 1 downTo maxOf(0, idx - 6)) {
            val c = texts[j].trim()
            if (c.isEmpty() || c.length > 24) continue
            if (c in IGNORE) continue
            if (isCommandLike(c)) continue
            return c
        }
        return null
    }

    private fun postEvent(json: String) {
        val urls = listOf(
            "http://127.0.0.1:3910/event",
            "http://10.0.2.2:3910/event",
        )
        for (u in urls) {
            try {
                val conn = (URL(u).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 1500
                    readTimeout = 1500
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                }
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(json) }
                if (conn.responseCode in 200..299) return
            } catch (_: Exception) {
            }
        }
    }

    companion object {
        private val IGNORE = setOf(
            "发送", "输入消息", "在线", "离线", "消息", "通讯录", "复制", "粘贴",
            "关闭功能菜单", "功能菜单",
        )

        private fun jsonStr(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

        private fun jsonArr(xs: List<String>): String =
            xs.joinToString(prefix = "[", postfix = "]") { jsonStr(it) }
    }
}
