/* PythonMarkerGuide.js — Python填空特殊标记指南 */
const PythonMarkerGuide = {
  template: `
    <div class="max-w-3xl mx-auto px-4 py-8">
      <div class="bg-white rounded-lg shadow p-6">
        <h2 class="text-2xl font-bold text-gray-800 mb-4">Python填空题特殊标记指南</h2>
        <div class="prose prose-sm max-w-none text-gray-700 space-y-4">
          <p>Python 填空题支持两种标记方式：</p>

          <h3 class="text-lg font-semibold mt-6">方式一：标准标记 <code class="bg-gray-100 px-1 rounded"># YOUR ANSWER</code></h3>
          <p>在参考文件需要填写的位置添加 <code># YOUR ANSWER</code> 注释。</p>
<pre class="bg-gray-900 text-green-400 p-4 rounded-lg text-sm overflow-auto">
def factorial(n):
    result = 1
    for i in range(1, n + 1):
        result *= i  # YOUR ANSWER
    return result
</pre>

          <h3 class="text-lg font-semibold mt-6">方式二：特殊标记 ①②③…</h3>
          <p>在参考文件需要填写的位置添加特殊标记（①, ②, ③, …, ⑩）。</p>
<pre class="bg-gray-900 text-green-400 p-4 rounded-lg text-sm overflow-auto">
def add(a, b):
    ①  # 填写返回值
</pre>
          <p>等价形式：<code>[1]</code>, <code>[2]</code>, <code>[3]</code>…<code>[10]</code></p>

          <h3 class="text-lg font-semibold mt-6">答案格式说明</h3>
          <ul class="list-disc pl-6 space-y-2">
            <li><strong>多个可接受答案</strong>：用 <code>//</code> 分隔<br/><code>result // res // output</code></li>
            <li><strong>多个填空组</strong>：用 <code>|</code> 分隔<br/><code>填空1答案|填空2答案</code></li>
          </ul>
        </div>
        <router-link to="/" class="inline-block mt-6 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">返回首页</router-link>
      </div>
    </div>
  `
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.PythonMarkerGuide = PythonMarkerGuide;
