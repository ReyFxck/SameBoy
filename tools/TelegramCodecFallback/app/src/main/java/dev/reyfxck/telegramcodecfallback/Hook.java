package dev.reyfxck.telegramcodecfallback;

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
        hookFactory(lpparam.classLoader, "androidx.media3.exoplayer.DefaultRenderersFactory");
    }

    private static void hookFactory(ClassLoader cl, String className) {
        Class<?> factory;
        try {
            factory = XposedHelpers.findClass(className, cl);
        } catch (Throwable ignored) {
            XposedBridge.log(TAG + ": not present: " + className);
            return;
        }

        XposedBridge.hookAllConstructors(factory, new XC_MethodHook() {
            @Override
            protected void afterHookedMethod(MethodHookParam param) {
                try {
                    XposedHelpers.callMethod(param.thisObject, "setEnableDecoderFallback", true);
                    XposedBridge.log(TAG + ": decoder fallback ENABLED for " + className);
                } catch (Throwable t) {
                    XposedBridge.log(TAG + ": failed for " + className + ": " + t);
                }
            }
        });

        XposedBridge.log(TAG + ": hooked " + className);
    }
}
