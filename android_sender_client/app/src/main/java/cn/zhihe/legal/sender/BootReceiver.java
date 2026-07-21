package cn.zhihe.legal.sender;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import cn.zhihe.legal.sender.config.GatewayConfigStore;
import cn.zhihe.legal.sender.gateway.GatewayService;

public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())
                && new GatewayConfigStore(context).isConfigured()) {
            GatewayService.start(context);
        }
    }
}
