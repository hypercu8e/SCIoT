// Host-only execution of the pinned Micro runtime. No device timing claims.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <string>
#include <vector>
#include "float_layer.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "CHECK failed line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)
namespace {
using Clock = std::chrono::steady_clock;
using Bytes = std::vector<uint8_t>;
constexpr size_t kCapacity = 49 * 49 * 48 * sizeof(float);
constexpr size_t kFloatArena = 8 * 1024 * 1024;
tflite::MicroErrorReporter reporter;
struct Arena {
  uint8_t* data = nullptr;
  size_t size;
  explicit Arena(size_t bytes) : size(bytes) { CHECK(posix_memalign(reinterpret_cast<void**>(&data), 16, bytes) == 0); }
  ~Arena() { std::free(data); }
  Arena(const Arena&) = delete;
  Arena& operator=(const Arena&) = delete;
};
template<class T> std::vector<T> read(const std::string& path) {
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  CHECK(f.good()); const auto length = f.tellg(); CHECK(length > 0);
  CHECK(size_t(length) % sizeof(T) == 0);
  std::vector<T> values(size_t(length) / sizeof(T));
  f.seekg(0); f.read(reinterpret_cast<char*>(values.data()), length); CHECK(f.good()); return values;
}
void save(const std::string& path, const void* data, size_t bytes) {
  std::ofstream f(path, std::ios::binary); f.write(static_cast<const char*>(data), bytes); CHECK(f.good());
}
double elapsed(Clock::time_point start) {
  return std::chrono::duration<double, std::micro>(Clock::now() - start).count();
}
std::unique_ptr<tflite::MicroInterpreter> create(const Bytes& binary, const tflite::MicroOpResolver& resolver, Arena& arena) {
  const auto* model = tflite::GetModel(binary.data()); CHECK(model->version() == TFLITE_SCHEMA_VERSION);
  auto* allocator = tflite::MicroAllocator::Create(arena.data, arena.size, &reporter); CHECK(allocator);
  std::unique_ptr<tflite::MicroInterpreter> result(new tflite::MicroInterpreter(model, resolver, allocator, &reporter));
  CHECK(result->AllocateTensors() == kTfLiteOk); return result;
}
void int8Spec(TfLiteTensor* t, std::istream& spec) {
  size_t bytes; float scale; int zero, dims; spec >> bytes >> scale >> zero >> dims;
  CHECK(spec.good() && t && t->type == kTfLiteInt8 && t->bytes == bytes);
  CHECK(t->params.scale == scale && t->params.zero_point == zero && t->dims->size == dims);
  for (int i = 0; i < dims; ++i) { int value; spec >> value; CHECK(value == t->dims->data[i]); }
}
struct Difference { size_t count; int maximum; };
Difference difference(const uint8_t* actual, const Bytes& expected) {
  size_t different = 0; int maximum = 0;
  for (size_t i = 0; i < expected.size(); ++i) {
    const int delta = std::abs(int(int8_t(actual[i])) - int(int8_t(expected[i])));
    different += delta != 0; maximum = std::max(maximum, delta);
  }
  return {different, maximum};
}
bool int8Run(const std::string& dir) {
  tflite::MicroMutableOpResolver<5> resolver;
  CHECK(resolver.AddAdd() == kTfLiteOk); CHECK(resolver.AddConv2D() == kTfLiteOk);
  CHECK(resolver.AddDepthwiseConv2D() == kTfLiteOk); CHECK(resolver.AddPad() == kTfLiteOk);
  CHECK(resolver.AddSoftmax() == kTfLiteOk);
  std::printf("{\"stages\":["); bool first = true, exactMatch = true;
  for (const std::string stage : {"full", "prefix", "suffix", "suffix_chain"}) {
    const std::string modelStage = stage == "suffix_chain" ? "suffix" : stage;
    auto binary = read<uint8_t>(dir + "/" + modelStage + ".tflite");
    Arena arena(512 * 1024); auto runtime = create(binary, resolver, arena);
    CHECK(runtime->inputs_size() == 1 && runtime->outputs_size() == 1);
    std::ifstream spec(dir + "/" + modelStage + ".spec"); CHECK(spec.good());
    auto* input = runtime->input(0); auto* output = runtime->output(0);
    int8Spec(input, spec); int8Spec(output, spec);
    size_t maximumDifferent = 0, failedInvocations = 0; int maximumDelta = 0;
    std::vector<Bytes> firstOutputs(3);
    // After the first mismatch continue diagnostics, but the command must fail.
    // Two warmups per input, then ten rounds of alternating inputs on one runtime.
    for (int round = -2; round < 10; ++round) for (int sample = 0; sample < 3; ++sample) {
      const std::string id = std::to_string(sample);
      const std::string source = stage == "suffix_chain" ? "/actual_prefix_" : "/input_" + modelStage + "_";
      const auto values = read<uint8_t>(dir + source + id + ".bin");
      const auto expected = read<uint8_t>(dir + "/expected_" + modelStage + "_" + id + ".bin");
      CHECK(values.size() == input->bytes && expected.size() == output->bytes);
      std::memcpy(input->data.int8, values.data(), values.size());
      CHECK(runtime->Invoke() == kTfLiteOk);
      const auto* actual = reinterpret_cast<uint8_t*>(output->data.int8);
      if (round == -2) firstOutputs[sample].assign(actual, actual + output->bytes);
      else CHECK(std::memcmp(actual, firstOutputs[sample].data(), output->bytes) == 0);
      const auto diff = difference(reinterpret_cast<uint8_t*>(output->data.int8), expected);
      maximumDifferent = std::max(maximumDifferent, diff.count); maximumDelta = std::max(maximumDelta, diff.maximum);
      failedInvocations += diff.count != 0; exactMatch = exactMatch && diff.count == 0;
      if (round == 9) save(dir + "/actual_" + stage + "_" + id + ".bin", output->data.int8, output->bytes);
    }
    if (!first) std::printf(","); first = false;
    std::printf("{\"stage\":\"%s\",\"arena_used_bytes\":%zu,\"checked_invocations\":36,\"mismatched_invocations\":%zu,\"max_mismatched_values\":%zu,\"max_integer_error\":%d}",
      stage.c_str(), runtime->arena_used_bytes(), failedInvocations, maximumDifferent, maximumDelta);
  }
  std::printf("],\"stable_across_alternating_inputs\":true,\"exact_match\":%s,\"hardware_verified\":false}\n", exactMatch ? "true" : "false");
  return exactMatch;
}
double maximumError = 0;
void close(const std::vector<float>& values, const std::vector<float>& expected, size_t bytes) {
  CHECK(bytes == expected.size() * sizeof(float));
  for (size_t i = 0; i < expected.size(); ++i) {
    const double error = std::abs(double(values[i]) - expected[i]);
    maximumError = std::max(maximumError, error);
    if (!std::isfinite(values[i]) || error > 1e-5 + 1e-5 * std::abs(double(expected[i]))) {
      std::fprintf(stderr, "Float mismatch value=%zu actual=%.9g expected=%.9g error=%.9g\n", i, values[i], expected[i], error);
      CHECK(false);
    }
  }
}
void floatRun(const std::string& dir, bool benchmark) {
  tflite::MicroMutableOpResolver<7> resolver;
  CHECK(resolver.AddAdd() == kTfLiteOk); CHECK(resolver.AddMul() == kTfLiteOk);
  CHECK(resolver.AddConv2D() == kTfLiteOk); CHECK(resolver.AddDepthwiseConv2D() == kTfLiteOk);
  CHECK(resolver.AddPad() == kTfLiteOk); CHECK(resolver.AddSoftmax() == kTfLiteOk);
  CHECK(resolver.AddRelu6() == kTfLiteOk);
  std::vector<Bytes> layers;
  std::vector<std::vector<float>> inputs;
  for (int i = 0; i < 59; ++i) layers.push_back(read<uint8_t>(dir + "/layer_" + std::to_string(i) + ".tflite"));
  for (int i = 0; i < 3; ++i) inputs.push_back(read<float>(dir + "/input_" + std::to_string(i) + ".bin"));
  Arena scratch(kFloatArena);
  // Untimed preparation probes for baseline memory and structural copy counts.
  std::vector<size_t> arenaUsed, copyBytes, outputBytes;
  for (const auto& binary : layers) {
    auto rt = create(binary, resolver, scratch);
    size_t copies = rt->output(0)->bytes;
    for (size_t j = 0; j < rt->inputs_size(); ++j) copies += rt->input(j)->bytes;
    copyBytes.push_back(copies); outputBytes.push_back(rt->output(0)->bytes);
    arenaUsed.push_back(rt->arena_used_bytes());
  }
  std::ofstream csv(dir + (benchmark ? "/timings.csv" : "/validation-timings.csv"));
  CHECK(csv.good()); csv << "split,sample,mode,round,total_us\n"; csv.precision(17);
  std::vector<float> work(kCapacity / sizeof(float)), residual(kCapacity / sizeof(float));
  std::printf("{\"splits\":["); bool first = true;
  for (int split : {0, 11, 25, 58}) {
    auto binary = read<uint8_t>(dir + "/prefix_" + std::to_string(split) + ".tflite");
    std::vector<std::vector<float>> references;
    for (int sample = 0; sample < 3; ++sample)
      references.push_back(read<float>(dir + "/reference_" + std::to_string(sample) + "_" + std::to_string(split) + ".bin"));
    Arena persistentArena(kFloatArena);
    const auto setupStart = Clock::now(); auto persistent = create(binary, resolver, persistentArena);
    const double setupUs = elapsed(setupStart);
    auto checkIO = [&](tflite::MicroInterpreter& rt) {
      CHECK(rt.inputs_size() == 1 && rt.outputs_size() == 1);
      CHECK(sciot::validFloatTensor(rt.input(0), inputs[0].size() * sizeof(float)));
      CHECK(sciot::validFloatTensor(rt.output(0), outputBytes[split]));
    };
    checkIO(*persistent);
    const int warmups = benchmark ? 5 : 0, runs = benchmark ? 30 : 2;
    const char* modes[] = {"separate", "grouped_recreated", "grouped_persistent"};
    for (int round = -warmups; round < runs; ++round) for (int sample = 0; sample < 3; ++sample) {
      for (int order = 0; order < 3; ++order) {
        const int mode = (order + round + warmups + sample) % 3;
        size_t bytes = inputs[sample].size() * sizeof(float);
        const auto start = Clock::now();
        std::memcpy(work.data(), inputs[sample].data(), bytes);
        if (mode == 0) {
          size_t residualBytes = 0;
          for (int layer = 0; layer <= split; ++layer) {
            size_t nextBytes = 0;
            CHECK(sciot::runFloatLayer(tflite::GetModel(layers[layer].data()), resolver,
                scratch.data, scratch.size, &reporter, work.data(), bytes, kCapacity,
                residual.data(), residualBytes, nextBytes) == sciot::LayerError::Ok);
            bytes = nextBytes;
            if (layer == 16 || layer == 34 || layer == 43) {
              std::memcpy(residual.data(), work.data(), bytes); residualBytes = bytes;
            }
          }
        } else {
          std::unique_ptr<tflite::MicroInterpreter> recreated;
          if (mode == 1) recreated = create(binary, resolver, scratch);
          auto& rt = mode == 1 ? *recreated : *persistent;
          auto* input = rt.input(0); auto* output = rt.output(0);
          CHECK(sciot::validFloatTensor(input, bytes) && sciot::validFloatTensor(output, outputBytes[split]));
          std::memcpy(input->data.f, work.data(), bytes);
          CHECK(rt.Invoke() == kTfLiteOk); bytes = output->bytes;
          std::memcpy(work.data(), output->data.f, bytes);
        }
        const double us = elapsed(start);
        close(work, references[sample], bytes);
        if (round >= 0) csv << split << ',' << sample << ',' << modes[mode] << ',' << round << ',' << us << '\n';
      }
    }
    size_t baselineCopies = inputs[0].size() * sizeof(float), maximumArena = 0;
    for (int layer = 0; layer <= split; ++layer) {
      baselineCopies += copyBytes[layer]; maximumArena = std::max(maximumArena, arenaUsed[layer]);
      if (layer == 16 || layer == 34 || layer == 43) baselineCopies += outputBytes[layer];
    }
    const size_t groupedCopies = 2 * inputs[0].size() * sizeof(float) + outputBytes[split];
    if (!first) std::printf(","); first = false;
    std::printf("{\"split\":%d,\"separate_explicit_copy_bytes\":%zu,\"grouped_explicit_copy_bytes\":%zu,"
      "\"separate_max_arena_used_bytes\":%zu,\"grouped_arena_used_bytes\":%zu,\"persistent_initial_setup_us\":%.9g,"
      "\"separate_preparations_per_frame\":%d,\"grouped_recreated_preparations_per_frame\":1,"
      "\"grouped_persistent_preparations_per_frame\":0}", split, baselineCopies, groupedCopies,
      maximumArena, persistent->arena_used_bytes(), setupUs, split + 1);
  }
  CHECK(csv.good());
  std::printf("],\"max_absolute_error\":%.17g,\"arena_capacity_bytes\":%zu,\"work_buffer_bytes\":%zu,"
    "\"separate_residual_buffer_bytes\":%zu,\"hardware_verified\":false}\n", maximumError, kFloatArena, kCapacity, kCapacity);
}
}  // namespace
int main(int argc, char** argv) {
  CHECK(argc == 3); const std::string mode = argv[1];
  if (mode == "int8") return int8Run(argv[2]) ? 0 : 2;
  else { CHECK(mode == "float-check" || mode == "float-bench"); floatRun(argv[2], mode == "float-bench"); }
}
