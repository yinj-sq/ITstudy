/**
 * FileUploader - 文件上传组件
 * 支持拖拽上传、文件列表显示、上传进度
 * Props: accept - 接受的文件类型, multiple - 是否多文件, uploadUrl - 上传地址
 * 使用 Axios + FormData 上传
 */
const FileUploader = {
  name: 'FileUploader',
  template: `
    <div class="w-full">
      <!-- 拖拽上传区域 -->
      <div
        @click="triggerFileInput"
        @dragover.prevent="onDragOver"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
        class="relative border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors"
        :class="isDragging
          ? 'border-blue-500 bg-blue-50'
          : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'"
      >
        <input
          ref="fileInputRef"
          type="file"
          :accept="accept"
          :multiple="multiple"
          @change="onFileSelected"
          class="hidden"
        />
        <div class="flex flex-col items-center">
          <i class="fas fa-cloud-upload-alt text-4xl mb-3"
            :class="isDragging ? 'text-blue-500' : 'text-gray-400'"></i>
          <p class="text-gray-600 font-medium">
            <template v-if="isDragging">释放鼠标以上传文件</template>
            <template v-else>拖拽文件到此处，或<span class="text-blue-600">点击选择文件</span></template>
          </p>
          <p class="text-sm text-gray-400 mt-1" v-if="accept">支持格式: {{ accept }}</p>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMessage" class="mt-3 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm flex items-center">
        <i class="fas fa-exclamation-circle mr-2"></i>
        {{ errorMessage }}
      </div>

      <!-- 文件列表 -->
      <div v-if="files.length > 0" class="mt-4 space-y-2">
        <div class="flex items-center justify-between mb-2">
          <h4 class="text-sm font-semibold text-gray-700">
            已选择 {{ files.length }} 个文件
          </h4>
          <div class="space-x-2">
            <button
              @click="uploadAll"
              :disabled="uploadingCount > 0"
              class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors"
              :class="uploadingCount > 0
                ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700'"
            >
              <i class="fas fa-upload mr-1"></i>
              {{ uploadingCount > 0 ? '上传中...' : '全部上传' }}
            </button>
            <button
              @click="clearFiles"
              :disabled="uploadingCount > 0"
              class="px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              :class="{ 'opacity-50 cursor-not-allowed': uploadingCount > 0 }"
            >
              <i class="fas fa-trash-alt mr-1"></i>
              清空列表
            </button>
          </div>
        </div>

        <div
          v-for="(fileItem, index) in files"
          :key="fileItem.id"
          class="flex items-center p-3 bg-gray-50 rounded-lg border border-gray-200"
        >
          <!-- 文件图标 -->
          <div class="flex-shrink-0 w-10 h-10 bg-gray-200 rounded-lg flex items-center justify-center mr-3">
            <i :class="getFileIconClass(fileItem.file.name)" class="text-lg"></i>
          </div>

          <!-- 文件信息 -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between">
              <p class="text-sm font-medium text-gray-700 truncate">{{ fileItem.file.name }}</p>
              <span class="text-xs text-gray-400 ml-2 flex-shrink-0">{{ formatFileSize(fileItem.file.size) }}</span>
            </div>

            <!-- 上传进度条 -->
            <div v-if="fileItem.status === 'uploading'" class="mt-1.5">
              <div class="w-full bg-gray-200 rounded-full h-1.5">
                <div
                  class="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                  :style="{ width: fileItem.progress + '%' }"
                ></div>
              </div>
              <span class="text-xs text-gray-400 mt-0.5 block">{{ fileItem.progress }}%</span>
            </div>

            <!-- 状态标签 -->
            <div v-else class="mt-1">
              <span v-if="fileItem.status === 'pending'" class="text-xs text-gray-400">等待上传</span>
              <span v-if="fileItem.status === 'success'" class="text-xs text-green-600">
                <i class="fas fa-check-circle mr-1"></i>上传成功
              </span>
              <span v-if="fileItem.status === 'error'" class="text-xs text-red-600">
                <i class="fas fa-exclamation-circle mr-1"></i>{{ fileItem.error || '上传失败' }}
              </span>
            </div>
          </div>

          <!-- 操作 -->
          <div class="flex-shrink-0 ml-3">
            <button
              v-if="fileItem.status === 'pending'"
              @click="uploadSingle(index)"
              class="px-2.5 py-1 text-xs font-medium text-blue-600 bg-blue-50 rounded hover:bg-blue-100 transition-colors"
            >
              上传
            </button>
            <button
              v-if="fileItem.status === 'pending'"
              @click="removeFile(index)"
              class="ml-1 px-2.5 py-1 text-xs font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
            >
              <i class="fas fa-times"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
  props: {
    accept: {
      type: String,
      default: ''
    },
    multiple: {
      type: Boolean,
      default: false
    },
    uploadUrl: {
      type: String,
      required: true
    },
    // 额外表单字段（如 question_id），随文件一起提交
    extraFields: {
      type: Object,
      default: () => ({})
    }
  },
  emits: ['uploaded'],
  setup(props, { emit }) {
    const { ref, reactive, computed, onMounted, onUnmounted } = Vue;
    const axios = window.axios;
    let unmounted = false;

    const fileInputRef = ref(null);
    const isDragging = ref(false);
    const errorMessage = ref('');
    const files = reactive([]);
    let fileIdCounter = 0;

    // 计算当前正在上传的文件数
    const uploadingCount = computed(() => {
      return files.filter(f => f.status === 'uploading').length;
    });

    // 触发文件选择对话框
    const triggerFileInput = () => {
      if (fileInputRef.value) {
        fileInputRef.value.click();
      }
    };

    // 拖拽进入
    const onDragOver = () => {
      isDragging.value = true;
    };

    // 拖拽离开
    const onDragLeave = () => {
      isDragging.value = false;
    };

    // 拖拽放下
    const onDrop = (event) => {
      isDragging.value = false;
      const droppedFiles = event.dataTransfer.files;
      if (droppedFiles && droppedFiles.length > 0) {
        addFiles(droppedFiles);
      }
    };

    // 文件选择回调
    const onFileSelected = (event) => {
      const selectedFiles = event.target.files;
      if (selectedFiles && selectedFiles.length > 0) {
        addFiles(selectedFiles);
      }
      // 重置 input 以允许重复选择同一文件
      if (fileInputRef.value) {
        fileInputRef.value.value = '';
      }
    };

    // 添加文件到列表
    const addFiles = (fileList) => {
      errorMessage.value = '';
      const newFiles = [];

      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i];

        // 验证文件类型
        if (props.accept && !isFileTypeAccepted(file, props.accept)) {
          errorMessage.value = `文件 "${file.name}" 的格式不被支持。支持的格式: ${props.accept}`;
          continue;
        }

        // 检查是否已存在同名文件
        const exists = files.some(f => f.file.name === file.name && f.file.size === file.size);
        if (exists) continue;

        newFiles.push({
          id: ++fileIdCounter,
          file: file,
          status: 'pending', // pending | uploading | success | error
          progress: 0,
          error: ''
        });
      }

      // 非 multiple 模式，只保留最后一个文件
      if (!props.multiple && newFiles.length > 0) {
        files.splice(0, files.length, newFiles[newFiles.length - 1]);
      } else {
        newFiles.forEach(f => files.push(f));
      }
    };

    // 检查文件类型是否匹配 accept 模式
    const isFileTypeAccepted = (file, acceptPattern) => {
      const patterns = acceptPattern.split(',').map(p => p.trim().toLowerCase());
      return patterns.some(pattern => {
        if (pattern.startsWith('.')) {
          // 扩展名匹配
          return file.name.toLowerCase().endsWith(pattern);
        }
        if (pattern.includes('/')) {
          // MIME 类型匹配 (含通配符如 image/*)
          const [type, subtype] = pattern.split('/');
          const fileType = file.type.split('/');
          if (type !== '*' && type !== fileType[0]) return false;
          if (subtype !== '*' && subtype !== fileType[1]) return false;
          return true;
        }
        return false;
      });
    };

    // 上传单个文件
    const uploadSingle = async (index) => {
      const fileItem = files[index];
      if (!fileItem || fileItem.status === 'uploading') return;

      fileItem.status = 'uploading';
      fileItem.progress = 0;
      fileItem.error = '';

      try {
        const formData = new FormData();
        formData.append('file', fileItem.file);
        // 附加额外表单字段（如 question_id）
        Object.entries(props.extraFields || {}).forEach(([key, value]) => {
          if (value !== undefined && value !== null) formData.append(key, value);
        });

        const response = await axios.post(props.uploadUrl, formData, {
          headers: {
            'Content-Type': 'multipart/form-data',
            'X-Requested-With': 'XMLHttpRequest'
          },
          onUploadProgress: (progressEvent) => {
            if (progressEvent.total) {
              fileItem.progress = Math.round((progressEvent.loaded / progressEvent.total) * 100);
            }
          }
        });

        fileItem.status = 'success';
        fileItem.progress = 100;

        // 通知父组件上传成功（携带响应数据 + 请求附加字段——
        // 上传耗时期间父组件可能已切题，extraFields.question_id 才是
        // 本次上传真正归属的题目）
        emit('uploaded', response.data, props.extraFields || {});

        // 自动移除已成功上传的文件（延迟一会儿让用户看到成功状态；
        // 组件卸载后不再操作，避免对已销毁的响应式数组写入）
        setTimeout(() => {
          if (unmounted) return;
          const idx = files.indexOf(fileItem);
          if (idx !== -1 && fileItem.status === 'success') {
            files.splice(idx, 1);
          }
        }, 2000);

        return response;
      } catch (error) {
        fileItem.status = 'error';
        fileItem.error = error.response?.data?.message || error.message || '上传失败';
        // 会话失效：跳转登录页（与 apiClient 401 处理一致）
        if (error.response?.status === 401) {
          if (window._appRouter) {
            window._appRouter.push('/');
          } else {
            window.location.href = '/';
          }
        }
        throw error;
      }
    };

    // 上传所有待上传的文件
    const uploadAll = async () => {
      const pendingFiles = files.map((f, idx) => ({ item: f, index: idx }))
        .filter(({ item }) => item.status === 'pending');

      for (const { item, index } of pendingFiles) {
        try {
          await uploadSingle(index);
        } catch (e) {
          // 继续上传下一个文件
          console.error('File upload failed:', item.file.name, e.message);
        }
      }
    };

    // 移除文件
    const removeFile = (index) => {
      if (files[index] && files[index].status !== 'uploading') {
        files.splice(index, 1);
      }
    };

    // 清空文件列表
    const clearFiles = () => {
      if (uploadingCount.value === 0) {
        files.splice(0, files.length);
        errorMessage.value = '';
      }
    };

    // 组件卸载后不再执行异步回调（如延迟移除文件列表项）
    onUnmounted(() => {
      unmounted = true;
    });

    // 获取文件图标类名
    const getFileIconClass = (fileName) => {
      const ext = fileName.split('.').pop()?.toLowerCase();
      const iconMap = {
        'pdf': 'fa-file-pdf text-red-500',
        'doc': 'fa-file-word text-blue-500',
        'docx': 'fa-file-word text-blue-500',
        'xls': 'fa-file-excel text-green-600',
        'xlsx': 'fa-file-excel text-green-600',
        'ppt': 'fa-file-powerpoint text-orange-500',
        'pptx': 'fa-file-powerpoint text-orange-500',
        'jpg': 'fa-file-image text-purple-500',
        'jpeg': 'fa-file-image text-purple-500',
        'png': 'fa-file-image text-purple-500',
        'gif': 'fa-file-image text-purple-500',
        'webp': 'fa-file-image text-purple-500',
        'svg': 'fa-file-image text-purple-500',
        'zip': 'fa-file-archive text-yellow-600',
        'rar': 'fa-file-archive text-yellow-600',
        '7z': 'fa-file-archive text-yellow-600',
        'py': 'fa-file-code text-gray-600',
        'js': 'fa-file-code text-yellow-500',
        'html': 'fa-file-code text-orange-500',
        'css': 'fa-file-code text-blue-500',
        'txt': 'fa-file-alt text-gray-500',
        'json': 'fa-file-code text-green-600',
        'mp4': 'fa-file-video text-blue-600',
        'mp3': 'fa-file-audio text-blue-400',
      };
      return iconMap[ext] || 'fa-file text-gray-400';
    };

    // 格式化文件大小
    const formatFileSize = (bytes) => {
      if (bytes === 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB'];
      const k = 1024;
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + units[i];
    };

    return {
      fileInputRef,
      isDragging,
      errorMessage,
      files,
      uploadingCount,
      triggerFileInput,
      onDragOver,
      onDragLeave,
      onDrop,
      onFileSelected,
      uploadSingle,
      uploadAll,
      removeFile,
      clearFiles,
      getFileIconClass,
      formatFileSize
    };
  }
};
