/**
 * QuestionCard - 题目展示卡片组件（只读展示）
 *
 * 支持 5 种题型渲染:
 *   单选题 / 多选题 / 判断题 / Python填空题 / 综合题
 *
 * Props:
 *   question   - 题目对象 {id, question_type, content, options, answer, score,
 *                image_options_dict, python_answers_dict, sub_questions}
 *   showAnswer - Boolean，是否显示答案
 *   userAnswer - 用户答案 (可选)
 *   score      - 得分 (可选)
 */
const QuestionCard = {
  name: 'QuestionCard',
  template: `
    <div class="bg-white shadow rounded-lg p-4 mb-3 border border-gray-200">
      <!-- 题目标题区 -->
      <div class="flex items-center justify-between mb-3 pb-2 border-b border-gray-100">
        <div class="flex items-center space-x-2">
          <!-- 题型标签 -->
          <span
            class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
            :class="typeBadgeClass"
          >
            <i :class="typeIcon" class="mr-1"></i>
            {{ questionTypeLabel }}
          </span>
          <!-- 题号 -->
          <span class="text-sm font-medium text-gray-700" v-if="questionIndex !== null">
            第 {{ questionIndex }} 题
          </span>
          <!-- 分值 -->
          <span v-if="question.score" class="text-xs text-gray-400">
            ({{ question.score }} 分)
          </span>
        </div>
        <!-- 用户得分 -->
        <div v-if="score !== null" class="flex items-center">
          <span
            class="text-sm font-bold"
            :class="score > 0 ? 'text-green-600' : 'text-red-600'"
          >
            {{ score }} / {{ question.score || '?' }}
          </span>
        </div>
      </div>

      <!-- 题目内容（经白名单过滤后渲染，支持富文本） -->
      <div class="mb-4 text-gray-800 leading-relaxed whitespace-pre-wrap" v-html="safeQuestionContent(question.content)"></div>

      <!-- 题目配图 -->
      <div v-if="questionImage" class="mb-4">
        <img :src="questionImage" alt="题目配图" class="max-w-full h-auto rounded-lg border"
          @error="onImageError" />
      </div>

      <!-- ==================== 单选题 ==================== -->
      <div v-if="questionType === '单选题'" class="space-y-2.5">
        <div
          v-for="(text, key) in parsedOptions"
          :key="key"
          class="flex items-center p-3 rounded-lg border-2 transition-colors"
          :class="getOptionClasses(key)"
        >
          <div
            class="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold mr-3"
            :class="getOptionIndicatorClasses(key)"
          >
            <template v-if="showAnswer && isCorrectAnswer(key)">
              <i class="fas fa-check"></i>
            </template>
            <template v-else-if="showAnswer && isUserWrongAnswer(key)">
              <i class="fas fa-times"></i>
            </template>
            <template v-else>
              {{ key }}
            </template>
          </div>
          <div class="flex-1 min-w-0">
            <!-- 图片选项 -->
            <template v-if="hasImageOptions && imageOptions[key]">
              <img :src="imageOptions[key]" :alt="'选项 ' + key" class="max-h-24 rounded" />
            </template>
            <template v-else>
              <span class="text-gray-700">{{ text }}</span>
            </template>
          </div>
        </div>
      </div>

      <!-- ==================== 多选题 ==================== -->
      <div v-else-if="questionType === '多选题'" class="space-y-2.5">
        <div
          v-for="(text, key) in parsedOptions"
          :key="key"
          class="flex items-center p-3 rounded-lg border-2 transition-colors"
          :class="getOptionClasses(key)"
        >
          <div
            class="flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold mr-3 border-2"
            :class="getOptionIndicatorClasses(key)"
          >
            <template v-if="showAnswer && isCorrectAnswer(key)">
              <i class="fas fa-check"></i>
            </template>
            <template v-else-if="showAnswer && isUserWrongAnswer(key)">
              <i class="fas fa-times"></i>
            </template>
            <template v-else>
              {{ key }}
            </template>
          </div>
          <div class="flex-1 min-w-0">
            <template v-if="hasImageOptions && imageOptions[key]">
              <img :src="imageOptions[key]" :alt="'选项 ' + key" class="max-h-24 rounded" />
            </template>
            <template v-else>
              <span class="text-gray-700">{{ text }}</span>
            </template>
          </div>
        </div>
        <!-- 多选提示 -->
        <p class="text-xs text-gray-400 mt-1">
          <i class="fas fa-info-circle mr-1"></i>多选题：可能包含多个正确答案
        </p>
      </div>

      <!-- ==================== 判断题 ==================== -->
      <div v-else-if="questionType === '判断题'" class="flex space-x-4">
        <div
          class="flex-1 p-4 rounded-lg border-2 text-center font-medium transition-colors cursor-default"
          :class="getJudgeOptionClass('正确')"
        >
          <i class="fas fa-check-circle mr-2 text-lg"></i>
          <span>正确</span>
          <div v-if="showAnswer && correctAnswerNormalized === '正确'" class="mt-1 text-xs font-normal text-green-600">
            <i class="fas fa-check mr-1"></i>正确答案
          </div>
          <div v-else-if="showAnswer && isUserWrongAnswer('正确')" class="mt-1 text-xs font-normal text-red-600">
            <i class="fas fa-times mr-1"></i>回答错误
          </div>
        </div>
        <div
          class="flex-1 p-4 rounded-lg border-2 text-center font-medium transition-colors cursor-default"
          :class="getJudgeOptionClass('错误')"
        >
          <i class="fas fa-times-circle mr-2 text-lg"></i>
          <span>错误</span>
          <div v-if="showAnswer && correctAnswerNormalized === '错误'" class="mt-1 text-xs font-normal text-green-600">
            <i class="fas fa-check mr-1"></i>正确答案
          </div>
          <div v-else-if="showAnswer && isUserWrongAnswer('错误')" class="mt-1 text-xs font-normal text-red-600">
            <i class="fas fa-times mr-1"></i>回答错误
          </div>
        </div>
      </div>

      <!-- ==================== Python填空题 ==================== -->
      <div v-else-if="questionType === 'Python填空题'" class="space-y-4">
        <!-- 代码块 -->
        <div class="relative group">
          <div class="flex items-center justify-between bg-gray-800 text-gray-300 rounded-t-lg px-4 py-2 text-xs">
            <span><i class="fab fa-python mr-1"></i>Python</span>
            <button @click="copyCode" class="hover:text-white transition-colors">
              <i class="fas fa-copy mr-1"></i>复制
            </button>
          </div>
          <pre class="bg-gray-900 text-green-400 p-4 rounded-b-lg overflow-x-auto text-sm leading-relaxed font-mono"><code>{{ question.content }}</code></pre>
        </div>

        <!-- 参考答案 -->
        <div v-if="showAnswer && hasPythonAnswers" class="bg-green-50 border border-green-200 rounded-lg p-4">
          <h4 class="text-sm font-semibold text-green-800 mb-2 flex items-center">
            <i class="fas fa-lightbulb mr-2"></i>参考答案
          </h4>
          <div class="space-y-1.5">
            <div
              v-for="(answer, blankId) in parsedPythonAnswers"
              :key="blankId"
              class="flex items-center text-sm"
            >
              <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-200 text-green-800 text-xs font-bold mr-2">
                {{ blankId }}
              </span>
              <code class="bg-white px-2.5 py-1 rounded border border-green-200 text-green-800 font-mono text-sm">
                {{ answer }}
              </code>
            </div>
          </div>
        </div>

        <!-- 用户答案 -->
        <div v-if="userAnswer" class="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h4 class="text-sm font-semibold text-blue-800 mb-2 flex items-center">
            <i class="fas fa-user mr-2"></i>你的答案
          </h4>
          <pre class="bg-white p-3 rounded border border-blue-100 text-sm font-mono overflow-x-auto">{{ userAnswer }}</pre>
        </div>
      </div>

      <!-- ==================== 填空题 ==================== -->
      <div v-else-if="questionType === '填空题'" class="space-y-4">
        <!-- 用户答案（逐空显示，此前该题型落入"未知题型"不渲染任何内容） -->
        <div v-if="userAnswer" class="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h4 class="text-sm font-semibold text-blue-800 mb-2 flex items-center">
            <i class="fas fa-user mr-2"></i>你的答案
          </h4>
          <div class="space-y-1.5">
            <div v-for="(ans, idx) in parsedFillUserAnswer" :key="idx" class="flex items-center text-sm">
              <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-200 text-blue-800 text-xs font-bold mr-2">{{ idx + 1 }}</span>
              <span class="bg-white px-2.5 py-1 rounded border border-blue-200">
                {{ ans || '（未作答）' }}
              </span>
            </div>
          </div>
        </div>
        <!-- 参考答案 -->
        <div v-if="showAnswer && parsedFillCorrectAnswer.length" class="bg-green-50 border border-green-200 rounded-lg p-4">
          <h4 class="text-sm font-semibold text-green-800 mb-2 flex items-center">
            <i class="fas fa-lightbulb mr-2"></i>参考答案
          </h4>
          <div class="space-y-1.5">
            <div v-for="(ans, idx) in parsedFillCorrectAnswer" :key="idx" class="flex items-center text-sm">
              <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-200 text-green-800 text-xs font-bold mr-2">{{ idx + 1 }}</span>
              <code class="bg-white px-2.5 py-1 rounded border border-green-200 text-green-800 font-mono text-sm">{{ ans }}</code>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== 综合题 ==================== -->
      <div v-else-if="questionType === '综合题'" class="space-y-4">
        <!-- 背景说明 -->
        <div class="bg-gray-50 border-l-4 border-blue-500 rounded-r-lg p-4">
          <h4 class="text-sm font-semibold text-gray-700 mb-1 flex items-center">
            <i class="fas fa-align-left mr-2 text-blue-500"></i>题目背景
          </h4>
          <p class="text-gray-600 text-sm leading-relaxed whitespace-pre-wrap">{{ question.content }}</p>
        </div>

        <!-- 子题目列表 -->
        <div v-if="hasSubQuestions" class="space-y-3">
          <h4 class="text-sm font-semibold text-gray-700 flex items-center">
            <i class="fas fa-list-ol mr-2 text-gray-400"></i>子题目
          </h4>
          <div
            v-for="(sub, index) in parsedSubQuestions"
            :key="sub.id || index"
            class="border rounded-lg p-3.5 ml-2 transition-colors"
            :class="getSubQuestionClass(sub, index)"
          >
            <!-- 子题头部 -->
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center space-x-2">
                <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-gray-200 text-gray-600 text-xs font-bold">
                  {{ index + 1 }}
                </span>
                <span class="text-sm font-medium text-gray-700">{{ getSubQuestionTypeLabel(sub) }}</span>
              </div>
              <span v-if="sub.score !== undefined && sub.score !== null" class="text-xs text-gray-400">
                {{ sub.score }} 分
              </span>
            </div>

            <!-- 子题内容 -->
            <p class="text-sm text-gray-700 mb-2 whitespace-pre-wrap">{{ sub.content }}</p>

            <!-- 子题选项（单选/多选） -->
            <div v-if="sub.options" class="space-y-1.5 ml-1">
              <div
                v-for="(optText, optKey) in parseSubQuestionOptions(sub.options)"
                :key="optKey"
                class="flex items-center text-sm"
              >
                <span class="font-medium text-gray-600 mr-2">{{ optKey }}.</span>
                <span class="text-gray-600">{{ optText }}</span>
              </div>
            </div>

            <!-- 学生子题作答与得分（综合题结果页） -->
            <div v-if="showAnswer && subUserAnswer(sub) !== null" class="mt-2 text-sm">
              <span class="text-gray-500">您的答案：</span>
              <span class="text-blue-700 font-medium whitespace-pre-wrap">{{ formatSubAnswer(sub) }}</span>
              <span v-if="subScoreValue(sub) !== null" class="ml-3 text-gray-500">
                得分：<span class="font-semibold">{{ subScoreValue(sub) }}</span> / {{ sub.score }}
              </span>
            </div>

            <!-- 子题答案 -->
            <div v-if="showAnswer && sub.answer" class="mt-2 pt-2 border-t border-gray-100">
              <span class="inline-flex items-center text-sm font-medium text-green-600">
                <i class="fas fa-check-circle mr-1.5"></i>
                答案: {{ sub.answer }}
              </span>
            </div>
          </div>
        </div>

        <!-- 空子题提示 -->
        <div v-else class="text-center py-4 text-gray-400 text-sm">
          <i class="fas fa-info-circle mr-1"></i>暂无子题目
        </div>

        <!-- 综合题结尾说明 / 参考代码 -->
        <div v-if="question.footer_content" class="mt-3 p-3 bg-gray-50 border rounded text-sm text-gray-700 whitespace-pre-wrap">
          <div class="font-medium text-gray-600 mb-1">参考代码 / 说明</div>
          {{ question.footer_content }}
        </div>
      </div>

      <!-- ==================== 未知题型 ==================== -->
      <div v-else class="py-4 text-center text-gray-400 text-sm">
        <i class="fas fa-question-circle mr-1"></i>
        未知题型: {{ question.question_type }}
      </div>

      <!-- 答案解析（仅 showAnswer 时显示） -->
      <div v-if="showAnswer && question.analysis" class="mt-4 pt-3 border-t border-gray-100">
        <div class="flex items-start">
          <i class="fas fa-comment-dots text-blue-500 mt-0.5 mr-2"></i>
          <div class="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">{{ question.analysis }}</div>
        </div>
      </div>
    </div>
  `,

  props: {
    question: {
      type: Object,
      required: true
    },
    showAnswer: {
      type: Boolean,
      default: false
    },
    userAnswer: {
      type: [String, Array, Object, Boolean],
      default: null
    },
    score: {
      type: Number,
      default: null
    },
    subAnswers: {
      type: Object,
      default: () => ({})
    },
    subScores: {
      type: Object,
      default: () => ({})
    },
    questionIndex: {
      type: Number,
      default: null
    }
  },

  setup(props) {
    const { computed, ref } = Vue;

    // ==================== 基础计算属性 ====================

    // 后端 question_type 使用英文标识（single/multiple/judge/fill/python_fill/comprehensive），
    // 此处统一映射为中文供模板分支使用；兼容历史中文数据（原样透传）。
    const TYPE_CN_MAP = {
      single: '单选题',
      multiple: '多选题',
      judge: '判断题',
      fill: '填空题',
      python_fill: 'Python填空题',
      comprehensive: '综合题'
    };

    const questionType = computed(() => {
      const raw = props.question?.question_type || '';
      return TYPE_CN_MAP[raw] || raw;
    });

    const questionTypeLabel = computed(() => {
      const labels = {
        '单选题': '单选题',
        '多选题': '多选题',
        '判断题': '判断题',
        'Python填空题': 'Python填空',
        '综合题': '综合题'
      };
      return labels[questionType.value] || questionType.value;
    });

    const typeBadgeClass = computed(() => {
      const map = {
        '单选题': 'bg-blue-100 text-blue-700',
        '多选题': 'bg-purple-100 text-purple-700',
        '判断题': 'bg-green-100 text-green-700',
        'Python填空题': 'bg-orange-100 text-orange-700',
        '综合题': 'bg-red-100 text-red-700'
      };
      return map[questionType.value] || 'bg-gray-100 text-gray-700';
    });

    const typeIcon = computed(() => {
      const map = {
        '单选题': 'fas fa-dot-circle',
        '多选题': 'fas fa-check-square',
        '判断题': 'fas fa-toggle-on',
        'Python填空题': 'fab fa-python',
        '综合题': 'fas fa-layer-group'
      };
      return map[questionType.value] || 'fas fa-question-circle';
    });

    // ==================== 选项处理 ====================

    /**
     * 解析 options 字段
     * 兼容三种格式（后端 normalize_options 输出管道串，模型存 JSON 字符串或对象）：
     *   - 对象 {A: 'text', B: 'text'}
     *   - JSON 字符串 '{"A": "text"}'
     *   - 管道字符串 "A.选项A|B.选项B"（字母+分隔符+内容）
     */
    const parsedOptions = computed(() => {
      const opts = props.question?.options;
      if (!opts) return {};
      if (typeof opts === 'object' && !Array.isArray(opts)) return opts;
      if (typeof opts === 'string') {
        const trimmed = opts.trim();
        if (trimmed.startsWith('{')) {
          try {
            const parsed = JSON.parse(trimmed);
            return parsed && typeof parsed === 'object' ? parsed : {};
          } catch {
            return {};
          }
        }
        if (trimmed.includes('|')) {
          const result = {};
          trimmed.split('|').forEach((part) => {
            const m = part.trim().match(/^([A-Za-z])\s*[.:、)）\]】\-]\s*(.*)$/s);
            if (m) {
              const key = m[1].toUpperCase();
              if (!(key in result)) result[key] = m[2].trim();
            }
          });
          return Object.keys(result).length ? result : {};
        }
      }
      return {};
    });

    /**
     * 题目配图：兼容 image_url（API 返回）与 image（历史字段）
     */
    const questionImage = computed(() => {
      return props.question?.image_url || props.question?.image || '';
    });

    /**
     * 选项图片映射：兼容 image_options_dict 与 image_options 字段
     */
    const hasImageOptions = computed(() => {
      const dict = props.question?.image_options_dict || props.question?.image_options;
      return dict && Object.keys(dict).length > 0;
    });

    const imageOptions = computed(() => {
      const dict = props.question?.image_options_dict || props.question?.image_options;
      if (!dict) return {};
      if (typeof dict === 'object') return dict;
      if (typeof dict === 'string') {
        try { return JSON.parse(dict); } catch { return {}; }
      }
      return {};
    });

    // ==================== 答案处理 ====================

    /**
     * 规范化正确答案
     */
    const correctAnswerNormalized = computed(() => {
      const ans = props.question?.answer;
      if (ans === undefined || ans === null) return '';
      if (typeof ans === 'string') return ans.trim();
      if (typeof ans === 'boolean') return ans ? '正确' : '错误';
      if (typeof ans === 'number') return String(ans);
      return '';
    });

    /**
     * 填空题：用户答案逐空（'|' 分隔）
     */
    const parsedFillUserAnswer = computed(() => {
      if (props.userAnswer === undefined || props.userAnswer === null) return [];
      return String(props.userAnswer).split('|').map(s => s.trim());
    });

    /**
     * 填空题：标准答案逐空（'|' 分隔）
     */
    const parsedFillCorrectAnswer = computed(() => {
      const ans = props.question?.answer;
      if (!ans) return [];
      return String(ans).split('|').map(s => s.trim());
    });

    /**
     * 多选题答案归一：与后端 scoring_service._normalize_multi_answer 同口径——
     * 标准答案存连续字母（'ABD'）、学生端可能存 'A|B|D'，此前仅 split(',')
     * 导致集合恒不匹配 → 正确/错误标记永不显示（SSR 版 result.html 正常）
     */
    function normalizeMultiSet(ans) {
      if (ans === undefined || ans === null || ans === '') return new Set()
      if (Array.isArray(ans)) ans = ans.join('')
      const str = String(ans)
      if (str.startsWith('[')) {
        try {
          const parsed = JSON.parse(str)
          if (Array.isArray(parsed)) return new Set(parsed.map(a => String(a).trim()))
        } catch {}
      }
      // 剥离所有分隔符/空白后逐字符展开为单字母集合
      return new Set(
        str.replace(/[^A-Za-z0-9]/g, '').toUpperCase().split('').filter(Boolean)
      )
    }

    /**
     * 正确答案集合（多选题用）
     */
    const correctAnswerSet = computed(() => normalizeMultiSet(props.question?.answer))

    /**
     * 用户答案集合（多选题用）
     */
    const userAnswerSet = computed(() => normalizeMultiSet(props.userAnswer))

    /**
     * 判断题的规范化答案
     */
    const judgeAnswer = computed(() => {
      const raw = correctAnswerNormalized.value;
      if (['正确', '对', 'true', 'True', 'T', '1', 'yes', 'Yes'].includes(raw)) return '正确';
      if (['错误', '错', 'false', 'False', 'F', '0', 'no', 'No'].includes(raw)) return '错误';
      return raw;
    });

    const userJudgeAnswer = computed(() => {
      if (!props.userAnswer) return null;
      const raw = String(props.userAnswer).trim();
      if (['正确', '对', 'true', 'True', 'T', '1', 'yes', 'Yes'].includes(raw)) return '正确';
      if (['错误', '错', 'false', 'False', 'F', '0', 'no', 'No'].includes(raw)) return '错误';
      return raw;
    });

    // ==================== Python 填空处理 ====================

    // Python 参考答案：兼容 python_answers_dict（历史字段）与 python_answers（API 返回）
    const pythonAnswersRaw = computed(() => {
      return props.question?.python_answers_dict || props.question?.python_answers;
    });

    const hasPythonAnswers = computed(() => {
      const pd = pythonAnswersRaw.value;
      if (!pd) return false;
      if (typeof pd === 'object' && Object.keys(pd).length > 0) return true;
      if (typeof pd === 'string') {
        try {
          const parsed = JSON.parse(pd);
          return typeof parsed === 'object' && Object.keys(parsed).length > 0;
        } catch { return false; }
      }
      return false;
    });

    const parsedPythonAnswers = computed(() => {
      const pd = pythonAnswersRaw.value;
      if (!pd) return {};
      if (typeof pd === 'object') return pd;
      try { return JSON.parse(pd); } catch { return {}; }
    });

    // ==================== 综合题处理 ====================

    const hasSubQuestions = computed(() => {
      return props.question?.sub_questions && props.question.sub_questions.length > 0;
    });

    const parsedSubQuestions = computed(() => {
      const sq = props.question?.sub_questions;
      if (!sq) return [];
      if (Array.isArray(sq)) return sq;
      if (typeof sq === 'string') {
        try { return JSON.parse(sq); } catch { return []; }
      }
      return [];
    });

    // ==================== 样式计算函数 ====================

    /**
     * 判断是否为正确答案的选项键
     */
    const isCorrectAnswer = (key) => {
      if (questionType.value === '多选题') {
        return correctAnswerSet.value.has(key);
      }
      if (questionType.value === '判断题') {
        return judgeAnswer.value === key;
      }
      return correctAnswerNormalized.value === key;
    };

    /**
     * 判断用户是否选了此选项且选错了
     */
    const isUserWrongAnswer = (key) => {
      if (!props.showAnswer || !props.userAnswer) return false;

      if (questionType.value === '多选题') {
        // 用户选了错误选项（多选了）
        if (userAnswerSet.value.has(key) && !correctAnswerSet.value.has(key)) return true;
        // 漏选不包括此场景，漏选不会显示为红色
        return false;
      }

      if (questionType.value === '判断题') {
        return userJudgeAnswer.value === key && judgeAnswer.value !== key;
      }

      // 单选题
      return String(props.userAnswer).trim() === key && correctAnswerNormalized.value !== key;
    };

    /**
     * 判断用户是否选中此选项
     */
    const isUserSelected = (key) => {
      if (!props.userAnswer) return false;

      if (questionType.value === '多选题') {
        return userAnswerSet.value.has(key);
      }
      if (questionType.value === '判断题') {
        return userJudgeAnswer.value === key;
      }
      return String(props.userAnswer).trim() === key;
    };

    /**
     * 获取选项的容器样式类
     */
    const getOptionClasses = (key) => {
      const classes = [];

      if (!props.showAnswer) {
        // 不显示答案时: 仅标记用户选择
        if (isUserSelected(key)) {
          classes.push('bg-blue-50', 'border-blue-300');
        } else {
          classes.push('bg-white', 'border-gray-200', 'hover:border-gray-300');
        }
        return classes;
      }

      // 显示答案时
      const isCorrect = isCorrectAnswer(key);
      const isWrong = isUserWrongAnswer(key);
      const isSelected = isUserSelected(key);

      if (isCorrect && isSelected) {
        classes.push('bg-green-50', 'border-green-500');
      } else if (isCorrect && !isSelected) {
        classes.push('bg-green-50', 'border-green-300');
      } else if (isWrong) {
        classes.push('bg-red-50', 'border-red-500');
      } else {
        classes.push('bg-white', 'border-gray-200');
      }

      return classes;
    };

    /**
     * 获取选项指示器（圆形/方形）的样式类
     */
    const getOptionIndicatorClasses = (key) => {
      const classes = [];

      if (!props.showAnswer) {
        if (isUserSelected(key)) {
          classes.push('bg-blue-600', 'text-white');
        } else {
          classes.push('bg-gray-100', 'text-gray-500');
        }
        return classes;
      }

      const isCorrect = isCorrectAnswer(key);
      const isWrong = isUserWrongAnswer(key);

      if (isCorrect) {
        classes.push('bg-green-500', 'text-white');
      } else if (isWrong) {
        classes.push('bg-red-500', 'text-white');
      } else if (isUserSelected(key)) {
        // 用户选了但既不是正确也不是错误（不太可能，但兜底）
        classes.push('bg-gray-500', 'text-white');
      } else {
        classes.push('bg-gray-100', 'text-gray-500');
      }

      return classes;
    };

    /**
     * 获取判断题选项样式
     */
    const getJudgeOptionClass = (value) => {
      if (!props.showAnswer) {
        if (userJudgeAnswer.value === value) {
          return 'bg-blue-50 border-blue-300 text-blue-700';
        }
        return 'bg-white border-gray-200 text-gray-500';
      }

      const isCorrect = judgeAnswer.value === value;
      const isUserChoice = userJudgeAnswer.value === value;

      if (isCorrect) {
        return 'bg-green-50 border-green-500 text-green-700 font-semibold';
      }
      if (isUserChoice) {
        return 'bg-red-50 border-red-500 text-red-700 font-semibold';
      }
      return 'bg-white border-gray-200 text-gray-400';
    };

    /**
     * 综合题子题：学生作答与得分（result 接口以 sub_<id> 为键）
     */
    const subUserAnswer = (sub) => {
      if (!sub || !props.subAnswers) return null;
      return Object.prototype.hasOwnProperty.call(props.subAnswers, sub.id)
        ? props.subAnswers[sub.id] : null;
    };
    const subScoreValue = (sub) => {
      if (!sub || !props.subScores) return null;
      return Object.prototype.hasOwnProperty.call(props.subScores, sub.id)
        ? props.subScores[sub.id] : null;
    };
    const formatSubAnswer = (sub) => {
      const value = subUserAnswer(sub);
      if (value === null || value === undefined || value === '') return '未作答';
      if (Array.isArray(value)) return value.join('、');
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
    };

    /**
     * 获取综合题子题的样式
     */
    const getSubQuestionClass = (sub, index) => {
      if (!props.showAnswer) {
        return 'border-gray-200 bg-white';
      }
      // 有逐子题得分时按得分判定；否则按学生作答与标准答案比对
      const score = subScoreValue(sub);
      if (score !== null && sub.score !== undefined && sub.score !== null) {
        return Number(score) >= Number(sub.score)
          ? 'border-green-200 bg-green-50'
          : 'border-red-200 bg-red-50';
      }
      const user = subUserAnswer(sub);
      if (user === null || user === '' || !sub.answer) {
        return 'border-gray-200 bg-white';
      }
      return String(user).trim().toUpperCase() === String(sub.answer).trim().toUpperCase()
        ? 'border-green-200 bg-green-50'
        : 'border-red-200 bg-red-50';
    };

    /**
     * 获取子题题型标签
     */
    const getSubQuestionTypeLabel = (sub) => {
      const type = sub.question_type || sub.type || '';
      // 后端子题类型为英文标识，统一映射为中文（兼容历史中文数据）
      const labels = {
        'single': '单选题', 'multiple': '多选题', 'judge': '判断题',
        'fill': '填空题', 'short_answer': '简答题', 'python_fill': 'Python填空',
        '单选题': '单选题', '多选题': '多选题', '判断题': '判断题',
        '填空题': '填空题', '简答题': '简答题'
      };
      return labels[type] || type || '题目';
    };

    /**
     * 解析子题的选项
     */
    const parseSubQuestionOptions = (options) => {
      if (!options) return {};
      if (typeof options === 'object') return options;
      if (typeof options === 'string') {
        // 子题选项经 normalize_options 统一存为管道串（'A.x|B.y'），
        // 此前仅 JSON.parse 必失败 → SPA 结果页综合题子题选项全部消失。
        // 与主题 parsedOptions（上方）管道串分支 / SSR result.html 同口径
        const result = {};
        options.split('|').forEach((part) => {
          const m = part.trim().match(/^([A-Za-z])\s*[.:、)）\]】\-]\s*(.*)$/s);
          if (m && !(m[1].toUpperCase() in result)) {
            result[m[1].toUpperCase()] = m[2].trim();
          }
        });
        return Object.keys(result).length ? result : {};
      }
      return {};
    };

    // ==================== 工具方法 ====================

    /**
     * 白名单过滤后渲染富文本题目内容
     */
    const safeQuestionContent = (value) => {
      return window.safeQuestionHtml ? window.safeQuestionHtml(value) : '';
    };

    /**
     * 复制代码到剪贴板
     */
    const copyCode = () => {
      if (!props.question?.content) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(props.question.content).catch(() => {
          fallbackCopy(props.question.content);
        });
      } else {
        fallbackCopy(props.question.content);
      }
    };

    const fallbackCopy = (text) => {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
      } catch (e) {
        console.error('复制失败:', e);
      }
      document.body.removeChild(textarea);
    };

    /**
     * 图片加载失败处理
     */
    const onImageError = (event) => {
      event.target.style.display = 'none';
    };

    return {
      // 计算属性
      questionType,
      questionTypeLabel,
      typeBadgeClass,
      typeIcon,
      parsedOptions,
      questionImage,
      hasImageOptions,
      imageOptions,
      correctAnswerNormalized,
      correctAnswerSet,
      userAnswerSet,
      judgeAnswer,
      userJudgeAnswer,
      hasPythonAnswers,
      parsedPythonAnswers,
      parsedFillUserAnswer,
      parsedFillCorrectAnswer,
      hasSubQuestions,
      parsedSubQuestions,
      // 方法
      isCorrectAnswer,
      isUserWrongAnswer,
      isUserSelected,
      getOptionClasses,
      getOptionIndicatorClasses,
      getJudgeOptionClass,
      getSubQuestionClass,
      getSubQuestionTypeLabel,
      parseSubQuestionOptions,
      subUserAnswer,
      subScoreValue,
      formatSubAnswer,
      copyCode,
      safeQuestionContent,
      onImageError
    };
  }
};
