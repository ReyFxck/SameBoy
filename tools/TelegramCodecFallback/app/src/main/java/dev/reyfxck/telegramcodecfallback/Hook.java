package dev.reyfxck.telegramcodecfallback;

import java.lang.reflect.Method;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

public final class Hook implements IXposedHookLoadPackage {
    private static final String TAG = "TelegramCodecFallback";

    @Override
    public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lpparam) {
        if (lpparam.packageName == null || !lpparam.packageName.startsWith("org.telegram.messenger")) {
            return;
        }

        hookFactory(lpparam.classLoader, "com.google.android.exoplayer2.DefaultRenderersFactory");
        hookSoftwareCodecCaps(lpparam.classLoader, "com.google.android.exoplayer2.mediacodec.MediaCodecInfo");

        // Future/current upstream Telegram variants that use Media3.
        hookFactory(lpparam.classLoader, "androidx.media3.exoplayer.DefaultRenderersFactory");
        hookSoftwareCodecCaps(lpparam.classLoader, "androidx.media3.exoplayer.mediacodec.MediaCodecInfo");
    }

    private static void hookFactory(ClassLoader cl, String className) {
        final Class<?> factory = XposedHelpers.findClassIfExists(className, cl);
        if (factory == null) {
            XposedBridge.log(TAG + ": not present: " + className);
            return;
        }

        final Method fallbackSetter;
        try {
            // Important: resolve the primitive boolean signature explicitly. The v1 hook used
            // XposedHelpers.callMethod(..., true), which was resolved as java.lang.Boolean on this
            // Telegram build and therefore missed setEnableDecoderFallback(boolean).
            fallbackSetter = XposedHelpers.findMethodExact(
                    factory,
                    "setEnableDecoderFallback",
                    boolean.class
            );
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": setter not found in " + className + ": " + t);
            return;
        }

        XposedBridge.hookAllConstructors(factory, new XC_MethodHook() {
            @Override
            protected void afterHookedMethod(MethodHookParam param) {
                try {
                    fallbackSetter.invoke(param.thisObject, true);
                    XposedBridge.log(TAG + ": decoder fallback ENABLED for " + className);
                } catch (Throwable t) {
                    XposedBridge.log(TAG + ": fallback enable failed for " + className + ": " + t);
                }
            }
        });

        XposedBridge.log(TAG + ": hooked factory " + className);
    }

    private static void hookSoftwareCodecCaps(ClassLoader cl, String className) {
        final Class<?> codecInfo = XposedHelpers.findClassIfExists(className, cl);
        if (codecInfo == null) {
            XposedBridge.log(TAG + ": codec info not present: " + className);
            return;
        }

        try {
            XposedHelpers.findAndHookMethod(
                    codecInfo,
                    "isVideoSizeAndRateSupportedV21",
                    int.class,
                    int.class,
                    double.class,
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            String name;
                            try {
                                name = (String) XposedHelpers.getObjectField(param.thisObject, "name");
                            } catch (Throwable ignored) {
                                return;
                            }

                            if (!"c2.android.avc.decoder".equals(name)) {
                                return;
                            }

                            int width = (Integer) param.args[0];
                            int height = (Integer) param.args[1];
                            double frameRate = (Double) param.args[2];

                            // Only override the metadata/capability answer for the Android software
                            // AVC decoder when the long side exceeds the QTI hardware limit. We do
                            // not lie about QTI hardware capability and we do not affect normal AVC.
                            if (width > 1920 || height > 1920) {
                                if (!Boolean.TRUE.equals(param.getResult())) {
                                    XposedBridge.log(TAG + ": allowing software AVC metadata for "
                                            + width + "x" + height + "@" + frameRate);
                                }
                                param.setResult(true);
                            }
                        }
                    }
            );
            XposedBridge.log(TAG + ": hooked software AVC capability check in " + className);
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": capability hook failed for " + className + ": " + t);
        }
    }
}
