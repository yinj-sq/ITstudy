/**
 * ConfirmModal - 确认对话框组件
 * 通用确认弹窗，支持自定义标题、消息内容
 * Emits: @confirm - 确认操作, @cancel - 取消操作
 */
const ConfirmModal = {
  name: 'ConfirmModal',
  template: `
    <div v-if="show" class="fixed inset-0 z-50 flex items-center justify-center">
      <!-- 遮罩层 -->
      <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity" @click="handleCancel"></div>
      <!-- 弹窗 -->
      <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full mx-4 z-10 transform transition-all">
        <!-- 头部 -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 class="text-lg font-semibold text-gray-900">
            {{ title || '确认操作' }}
          </h3>
          <button @click="handleCancel" class="text-gray-400 hover:text-gray-600 transition-colors">
            <i class="fas fa-times"></i>
          </button>
        </div>
        <!-- 消息内容 -->
        <div class="px-6 py-4">
          <p class="text-gray-600">{{ message }}</p>
        </div>
        <!-- 操作按钮 -->
        <div class="flex justify-end space-x-3 px-6 py-4 bg-gray-50 rounded-b-lg">
          <button @click="handleCancel"
            class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
            取消
          </button>
          <button @click="handleConfirm"
            class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors">
            确认
          </button>
        </div>
      </div>
    </div>
  `,
  props: {
    show: {
      type: Boolean,
      default: false
    },
    title: {
      type: String,
      default: '确认操作'
    },
    message: {
      type: String,
      default: '确定要执行此操作吗？'
    }
  },
  setup(props, { emit }) {
    const handleConfirm = () => {
      emit('confirm');
    };

    const handleCancel = () => {
      emit('cancel');
    };

    return {
      handleConfirm,
      handleCancel
    };
  }
};
