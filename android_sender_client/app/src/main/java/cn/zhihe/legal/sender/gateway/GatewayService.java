package cn.zhihe.legal.sender.gateway;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import cn.zhihe.legal.sender.R;
import cn.zhihe.legal.sender.automation.AutomationCoordinator;
import cn.zhihe.legal.sender.config.GatewayConfigStore;
import cn.zhihe.legal.sender.config.GatewayEndpoint;
import java.util.concurrent.TimeUnit;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;

public final class GatewayService extends Service {
    public static final String ACTION_RELOAD = "cn.zhihe.legal.sender.action.RELOAD";
    private static final String CHANNEL_ID = "gateway_connection";
    private static final int NOTIFICATION_ID = 1001;
    private static final long MAX_RECONNECT_DELAY_MS = 30_000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable reconnectTask = this::connect;
    private OkHttpClient httpClient;
    private WebSocket webSocket;
    private int reconnectAttempt;
    private int connectionGeneration;

    public static void start(Context context) {
        Intent intent = new Intent(context, GatewayService.class);
        intent.setAction(ACTION_RELOAD);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        startForeground(
                NOTIFICATION_ID,
                notification(getString(R.string.gateway_connecting))
        );
        httpClient = new OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .pingInterval(20, TimeUnit.SECONDS)
                .retryOnConnectionFailure(true)
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        connect();
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        connectionGeneration += 1;
        if (webSocket != null) {
            webSocket.close(1000, "service stopped");
            webSocket = null;
        }
        if (httpClient != null) {
            httpClient.dispatcher().executorService().shutdown();
            httpClient.connectionPool().evictAll();
        }
        super.onDestroy();
    }

    private void connect() {
        handler.removeCallbacks(reconnectTask);
        GatewayEndpoint endpoint;
        try {
            endpoint = new GatewayConfigStore(this).load();
        } catch (IllegalArgumentException exception) {
            updateNotification(getString(R.string.gateway_disconnected));
            return;
        }

        int generation = ++connectionGeneration;
        if (webSocket != null) {
            webSocket.cancel();
            webSocket = null;
        }
        updateNotification(getString(R.string.gateway_connecting));
        Request request = new Request.Builder().url(endpoint.websocketUrl()).build();
        httpClient.newWebSocket(request, new DeviceSocketListener(generation));
    }

    private void scheduleReconnect(int generation) {
        if (generation != connectionGeneration) {
            return;
        }
        webSocket = null;
        updateNotification(getString(R.string.gateway_disconnected));
        reconnectAttempt = Math.min(reconnectAttempt + 1, 6);
        long delay = Math.min(
                1_000L << Math.max(0, reconnectAttempt - 1),
                MAX_RECONNECT_DELAY_MS
        );
        handler.removeCallbacks(reconnectTask);
        handler.postDelayed(reconnectTask, delay);
    }

    private void handleCommand(WebSocket socket, String rawMessage) {
        final SendCommand command;
        try {
            command = SendCommand.parse(rawMessage);
        } catch (CommandProtocolException exception) {
            if (!exception.messageId().isEmpty()) {
                socket.send(CommandReceipt.failure(
                        exception.messageId(),
                        4002,
                        exception.getMessage()
                ));
            }
            return;
        }

        boolean accepted = AutomationCoordinator.getInstance().submit(
                command,
                (success, reason) -> socket.send(
                        success
                                ? CommandReceipt.success(command)
                                : CommandReceipt.failure(command.messageId(), 5004, reason)
                )
        );
        if (!accepted) {
            socket.send(CommandReceipt.failure(
                    command.messageId(),
                    5002,
                    "发送端正在执行其他指令"
            ));
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.gateway_channel_name),
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setShowBadge(false);
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private Notification notification(String status) {
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(status)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .build();
    }

    private void updateNotification(String status) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.notify(NOTIFICATION_ID, notification(status));
    }

    private final class DeviceSocketListener extends WebSocketListener {
        private final int generation;

        private DeviceSocketListener(int generation) {
            this.generation = generation;
        }

        @Override
        public void onOpen(WebSocket socket, Response response) {
            if (generation != connectionGeneration) {
                socket.close(1000, "stale connection");
                return;
            }
            webSocket = socket;
            reconnectAttempt = 0;
            handler.post(() -> updateNotification(getString(R.string.gateway_connected)));
        }

        @Override
        public void onMessage(WebSocket socket, String text) {
            if (generation == connectionGeneration) {
                handleCommand(socket, text);
            }
        }

        @Override
        public void onClosed(WebSocket socket, int code, String reason) {
            handler.post(() -> scheduleReconnect(generation));
        }

        @Override
        public void onFailure(WebSocket socket, Throwable error, Response response) {
            handler.post(() -> scheduleReconnect(generation));
        }
    }
}
