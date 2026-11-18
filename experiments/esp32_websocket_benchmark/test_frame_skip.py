"""Regression coverage for policy decisions and replay event accounting."""

from pathlib import Path
import subprocess

import numpy as np

from frame_skip_replay import summarize_policy, uniform_selection, visual_selection


def test_firmware_reference_advances_only_after_acknowledgment(tmp_path):
    source = tmp_path / 'policy.cpp'
    source.write_text(r'''
#include "frame_skip.h"
#include <cassert>
#include <algorithm>

int main() {
  using namespace frame_skip;
  int8_t image[pixels] = {};
  int8_t storage[2 * pixels];
  Policy policy({Mode::Active, Metric::Global, 4, 1500}, storage);
  assert(policy.decide(image, 0).reason == Reason::First);
  policy.stage(image);
  assert(policy.decide(image, 0).reason == Reason::First);
  policy.acknowledge(0, 0);
  std::fill_n(image, pixels, 3);
  assert(policy.decide(image, 500000).reason == Reason::Similar);
  std::fill_n(image, pixels, 4);
  assert(policy.decide(image, 1000000).reason == Reason::Change);
  policy.stage(image);
  std::fill_n(image, pixels, 5);
  assert(policy.referenceFrame() == 0);
  assert(policy.decide(image, 1000000).difference == 5);
  policy.acknowledge(1000000, 2);
  assert(policy.referenceFrame() == 2);
  assert(policy.decide(image, 2499999).difference == 1);
  assert(policy.decide(image, 2499999).reason == Reason::Similar);
  assert(policy.decide(image, 2500000).reason == Reason::Refresh);

  Policy local({Mode::Shadow, Metric::Local, 4, 1500}, storage);
  std::fill_n(image, pixels, 0);
  local.stage(image);
  local.acknowledge(0, 0);
  for (int y = 88; y < 96; ++y) std::fill_n(image + y * side + 88, tile, 4);
  assert(local.decide(image, 500000).reason == Reason::Change);
  assert(difference(image, storage + pixels, Metric::Global) == 0);
}
''')
    binary = tmp_path / 'policy'
    subprocess.run([
        'g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-I', str(Path(__file__).parent / 'idf/src'), str(source), '-o', str(binary)], check=True)
    subprocess.run([binary], check=True)


def test_replay_change_accumulates_and_refreshes_at_boundary():
    timestamps = np.arange(6) * 500_000
    images = np.broadcast_to(np.array([0, 2, 4, 4, 4, 4])[:, None, None], (6, 96, 96))
    assert visual_selection(images, timestamps, 'global', 4, 1500).tolist() == [0, 0, 2, 2, 2, 5]
    images = np.zeros((3, 96, 96), dtype=np.int8)
    images[1, 88:, 88:] = 4
    assert visual_selection(images, timestamps[:3], 'local', 4, 1500).tolist() == [0, 1, 2]
    assert visual_selection(images, timestamps[:3], 'global', 4, 1500).tolist() == [0, 0, 0]


def test_stale_presence_does_not_credit_a_new_event():
    presence = np.array([[True], [False], [True], [False]])
    stale = summarize_policy(np.arange(4) * 1000, presence, presence, np.array([0, 0, 0, 3]))
    assert stale['missed_events'] == 1
    assert stale['events'][0]['disappearance_censored']
    assert stale['stale_presence_samples'] == 1
    assert stale['events'][1]['onset_delay_ms'] is None
    assert uniform_selection(7, 3).tolist() == [0, 0, 2, 2, 4, 4, 4]
