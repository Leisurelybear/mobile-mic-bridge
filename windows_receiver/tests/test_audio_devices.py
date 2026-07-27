from mobile_mic_receiver.audio import is_recommended_output_name


def test_recommended_output_names() -> None:
    assert is_recommended_output_name('CABLE Input (VB-Audio Virtual Cable)')
    assert is_recommended_output_name('Voicemeeter Input')
    assert not is_recommended_output_name('Speakers (Realtek HD Audio output)')
    assert not is_recommended_output_name('Microsoft Sound Mapper - Output')
