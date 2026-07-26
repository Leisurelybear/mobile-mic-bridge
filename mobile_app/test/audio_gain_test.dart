import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_mic_bridge/audio_gain.dart';

void main() {
  test('applies pcm16 gain and clamps samples', () {
    final result = applyPcm16Gain(
      <int>[0xe8, 0x03, 0x18, 0xfc, 0xff, 0x7f],
      2,
    );

    expect(result, <int>[0xd0, 0x07, 0x30, 0xf8, 0xff, 0x7f]);
  });

  test('zero gain mutes samples', () {
    expect(applyPcm16Gain(<int>[0x34, 0x12], 0), <int>[0, 0]);
  });
}
