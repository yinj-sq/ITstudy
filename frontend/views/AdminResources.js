/* AdminResources.js — 学习资源管理 */
const AdminResources = {
  template: `
    <div class="max-w-5xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">学习资源管理</h2>
        <div class="space-x-2">
          <a href="/admin/resources/upload_page" class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm inline-block">
            <i class="fas fa-upload mr-1"></i>上传资源文件
          </a>
          <button @click="showAdd = true" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">添加资源链接</button>
        </div>
      </div>

      <div v-if="showAdd" class="bg-white rounded-lg shadow p-4 mb-4 space-y-3">
        <input v-model="form.title" type="text" placeholder="资源标题"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg" />
        <input v-model="form.url" type="text" placeholder="资源链接 (http://...)"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg" />
        <p class="text-xs text-gray-400">也可以选择上传资源文件夹</p>
        <div class="flex space-x-2">
          <button @click="addResource" :disabled="!form.title||!form.url||saving"
            class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">{{ saving ? '保存中...' : '保存' }}</button>
          <button @click="showAdd=false;form.title='';form.url=''" :disabled="saving" class="px-4 py-2 bg-gray-100 rounded-lg">取消</button>
        </div>
      </div>

      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
      </div>
      <EmptyState v-else-if="!resources.length" message="暂无学习资源" />

      <div v-else class="grid gap-4 md:grid-cols-2">
        <div v-for="res in resources" :key="res.id" class="bg-white rounded-lg shadow p-4">
          <div v-if="editingId === res.id" class="space-y-2">
            <input v-model="editForm.title" class="w-full px-2 py-1 border rounded text-sm" />
            <input v-model="editForm.url" class="w-full px-2 py-1 border rounded text-sm" />
            <div class="flex space-x-2">
              <button @click="updateResource(res.id)" class="text-green-600 text-sm hover:underline">保存</button>
              <button @click="editingId = null" class="text-gray-500 text-sm hover:underline">取消</button>
            </div>
          </div>
          <template v-else>
            <h3 class="font-semibold text-gray-800">{{ res.title }}</h3>
            <p class="text-sm text-gray-400 truncate mt-1">{{ res.url }}</p>
            <div class="flex space-x-3 mt-3">
              <button @click="startEdit(res)" class="text-blue-600 text-sm hover:underline">编辑</button>
              <button @click="deleteResource(res.id)" class="text-red-600 text-sm hover:underline">删除</button>
              <a :href="safeUrl(res.url)" target="_blank" rel="noopener" class="text-gray-500 text-sm hover:underline">访问</a>
            </div>
          </template>
        </div>
      </div>
    </div>
  `,
  setup() {
    const resources = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')
    const showAdd = Vue.ref(false)
    const editingId = Vue.ref(null)
    const form = Vue.reactive({ title: '', url: '' })
    const editForm = Vue.reactive({ title: '', url: '' })
    const saving = Vue.ref(false)

    async function load() {
      loadError.value = ''
      try {
        const { data } = await resourcesAPI.list()
        if (data.success) resources.splice(0, resources.length, ...data.data)
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
      finally { loading.value = false }
    }

    async function addResource() {
      if (saving.value) return
      saving.value = true
      try {
        const { data } = await resourcesAPI.create({ ...form })
        if (data.success) { showAdd.value = false; form.title = ''; form.url = ''; await load() }
      } catch (e) { alert('添加失败') }
      finally { saving.value = false }
    }

    // 协议白名单校验：拦截 javascript: 等危险协议
    function safeUrl(url) {
      if (window.isSafeUrl && url && !window.isSafeUrl(url)) return '#'
      return url
    }

    function startEdit(r) { editingId.value = r.id; editForm.title = r.title; editForm.url = r.url }

    async function updateResource(id) {
      try {
        await resourcesAPI.update(id, { ...editForm })
        editingId.value = null
        await load()
      } catch (e) { alert('更新失败') }
    }

    async function deleteResource(id) {
      if (!confirm('确定删除？')) return
      try { await resourcesAPI.delete(id); await load() }
      catch (e) { alert('删除失败') }
    }

    Vue.onMounted(load)
    return { resources, loading, loadError, showAdd, editingId, form, editForm, saving, addResource, startEdit, updateResource, deleteResource, safeUrl }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminResources = AdminResources;
