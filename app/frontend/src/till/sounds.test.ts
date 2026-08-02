// The counter's two tones (#247, grill Q8).
//
// The rule and the gate are what is worth pinning: which sound a scan earns, and
// that a muted till makes none. The oscillator itself is a browser's job - what
// is asserted about it here is only that the two tones are actually different,
// because "a distinctly different buzz" is the whole of the ruling and two
// near-identical beeps would pass every other test in this file.

import { describe, expect, it } from "vitest";

import { playTone, TONES, toneForScan } from "./sounds";
import type { ToneAudio } from "./sounds";

describe("which sound a scan earns", () => {
  it("ticks when the piece landed and needs nothing", () => {
    expect(toneForScan({ resolved: true, ambiguous: false })).toBe("tick");
  });

  it("buzzes when nothing matched the tag", () => {
    expect(toneForScan({ resolved: false, ambiguous: false })).toBe("buzz");
  });

  it("buzzes when the line landed but the season question is waiting", () => {
    // The line *is* on the bill - this is grill Q8's second buzz case, and the
    // easy mistake is to tick it because a line appeared.
    expect(toneForScan({ resolved: true, ambiguous: true })).toBe("buzz");
  });
});

describe("the two tones", () => {
  it("are not near neighbours - a cashier looking away must tell them apart", () => {
    expect(TONES.buzz.wave).not.toBe(TONES.tick.wave);
    expect(TONES.buzz.hz).toBeLessThan(TONES.tick.hz / 2);
    expect(TONES.buzz.ms).toBeGreaterThan(TONES.tick.ms * 2);
  });
});

/** An audio device that writes down what it was asked to play. */
function recorder(): { audio: ToneAudio; played: { wave: string; hz: number }[] } {
  const played: { wave: string; hz: number }[] = [];
  const node = { connect: () => undefined };
  const audio: ToneAudio = {
    currentTime: 0,
    state: "running",
    resume: () => undefined,
    destination: {},
    createOscillator: () => {
      const osc = {
        type: "",
        frequency: { value: 0 },
        ...node,
        start: () => played.push({ wave: osc.type, hz: osc.frequency.value }),
        stop: () => undefined,
      };
      return osc;
    },
    createGain: () => ({
      gain: {
        value: 0,
        setValueAtTime: () => undefined,
        exponentialRampToValueAtTime: () => undefined,
      },
      ...node,
    }),
  };
  return { audio, played };
}

describe("playing one", () => {
  it("makes the tone it was asked for", () => {
    const { audio, played } = recorder();

    playTone("buzz", false, () => audio);

    expect(played).toEqual([{ wave: TONES.buzz.wave, hz: TONES.buzz.hz }]);
  });

  it("makes no sound at all on a muted till", () => {
    const { audio, played } = recorder();
    let opened = 0;

    playTone("tick", true, () => {
      opened += 1;
      return audio;
    });

    expect(played).toEqual([]);
    // Not even the audio device is touched: a muted counter should not be asked
    // for one, let alone have a browser start one up under an autoplay prompt.
    expect(opened).toBe(0);
  });

  it("carries on when the browser has no audio at all", () => {
    // A kiosk with no sound device, or a tab the autoplay policy has shut out.
    // The scan is what matters; the sound is a courtesy.
    expect(() => playTone("tick", false, () => null)).not.toThrow();
  });

  it("carries on when the audio device throws", () => {
    expect(() =>
      playTone("tick", false, () => {
        throw new Error("no output device");
      }),
    ).not.toThrow();
  });

  it("wakes a context the browser had suspended", () => {
    const { audio, played } = recorder();
    let resumed = 0;

    playTone("tick", false, () => ({ ...audio, state: "suspended", resume: () => (resumed += 1) }));

    // The first scan of a shift is the one most worth confirming.
    expect(resumed).toBe(1);
    expect(played).toHaveLength(1);
  });
});
