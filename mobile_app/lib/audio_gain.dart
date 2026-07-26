import 'dart:typed_data';

Uint8List applyPcm16Gain(List<int> input, double gain) {
  final output = Uint8List(input.length);
  final sampleBytes = input.length - (input.length % 2);
  for (var offset = 0; offset < sampleBytes; offset += 2) {
    var sample = input[offset] | (input[offset + 1] << 8);
    if (sample >= 0x8000) sample -= 0x10000;
    var scaled = (sample * gain).round().clamp(-32768, 32767).toInt();
    if (scaled < 0) scaled += 0x10000;
    output[offset] = scaled & 0xff;
    output[offset + 1] = (scaled >> 8) & 0xff;
  }
  if (sampleBytes != input.length) {
    output[input.length - 1] = input.last;
  }
  return output;
}
