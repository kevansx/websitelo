$(".accountLotteryLink").on("click", function(e){
	e.stopPropagation();
});

/*------------------------------------ START: ACCOUNT PAGE NAVIGATION ------------------------------------*/
let searchParams = window.location.href;
if(searchParams.indexOf('#wallet') >= 0){
	$("#myDetailsSection,#lotteryOrderSection,#notificationSection").hide();
	$("#myDetailsTab,#lotteryOrderTab,#notificationTab").removeClass('accountTabActive');
	$("#lotteryWalletSection").show();
	$("#lotteryWalletTab").addClass('accountTabActive');
} else if(searchParams.indexOf('#orders') >= 0){
	$("#myDetailsSection,#lotteryWalletSection,#notificationSection").hide();
	$("#myDetailsTab,#notificationTab,#lotteryWalletTab").removeClass('accountTabActive');
	$("#lotteryOrderSection").show();
	$("#lotteryOrderTab").addClass('accountTabActive');
} else if(searchParams.indexOf('#notifications') >= 0){
	$("#myDetailsSection,#lotteryWalletSection,#lotteryOrderSection").hide();
	$("#myDetailsTab,#lotteryOrderTab,#lotteryWalletTab").removeClass('accountTabActive');
	$("#notificationSection").show();
	$("#notificationTab").addClass('accountTabActive');
} else if(searchParams.indexOf('#winnings') >= 0){ // this is from the email link
	goToWinningsSection();
	cleanURL();
} else if(searchParams.indexOf('#showOrderId') >= 0){ // this is from the email link
	goToOrdersSection();
	cleanURL();
} else if(searchParams.indexOf('#showAccountProfile') >= 0){ // this is from the email link
	goToProfileSection();
	cleanURL();
} else if(searchParams.indexOf('#showAccountLimits') >= 0){ // this is from the email link
	goToLimitsSection();
	cleanURL();
} else {
	$("#lotteryWalletSection,#lotteryOrderSection,#notificationSection").hide();
	$("#lotteryOrderTab,#notificationTab,#lotteryWalletTab").removeClass('accountTabActive');
	$("#myDetailsSection").show();
	$("#myDetailsTab").addClass('accountTabActive');	
}

function goToLimitsSection(){
	$("#lotteryOrderSection,#lotteryWalletSection,#notificationSection").hide();
	$("#lotteryOrderTab,#lotteryWalletTab,#notificationTab").removeClass('accountTabActive');
	$("#myDetailsSection").show();
	$("#myDetailsTab").addClass('accountTabActive');	
	$("#setLimitsDropdown").addClass("active");
}

$("#showAccountProfile").on("click",function(){
	goToProfileSection();
});

function goToProfileSection(){
	$("#lotteryOrderSection,#lotteryWalletSection,#notificationSection").hide();
	$("#lotteryOrderTab,#lotteryWalletTab,#notificationTab").removeClass('accountTabActive');
	$("#myDetailsSection").show();
	$("#myDetailsTab").addClass('accountTabActive');	
	$("#customerProfileDropDown").addClass("active");
	$([document.documentElement, document.body]).animate({
		scrollTop: $("#customerProfileDropDown").offset().top
	}, 1500);
	//var country = $("#acctDetailsCountry").val();
	//var city = $("#acctDetailsCurrentCity").val();
	//setPaymentAddress(city,"acctDetailsCity",country,"acctDetailsCountry");
}

function goToOrdersSection(){
	$("#myDetailsSection,#lotteryWalletSection,#notificationSection").hide();
	$("#myDetailsTab,#lotteryWalletTab,#notificationTab").removeClass('accountTabActive');
	$("#lotteryOrderSection").show();
	$("#lotteryOrderTab").addClass('accountTabActive');	
	$("#orderHistoryDropDown").addClass("active");
	if($("#orderHistoryNo").val()){
		console.log("here");
		setTimeout( function () { 
		$('#searchOrderHistoryButton').trigger('click');
		}, 1500);
	} else {
		console.log("not here");
	}
	$([document.documentElement, document.body]).animate({
		scrollTop: $("#orderHistoryDropDown").offset().top
	}, 1500);
}
	
function accountPageDisplay(div){
	if(div == 1){
		$(".accountTab").hide();
		$("#lotteryWalletTab,#lotteryOrderTab,#notificationTab").removeClass('accountTabActive');
		$("#myDetailsSection").show();
		$("#myDetailsTab").addClass('accountTabActive');
	} else if(div == 2){
		$(".accountTab").hide();
		$("#myDetailsTab,#lotteryOrderTab,#notificationTab").removeClass('accountTabActive');
		$("#lotteryWalletSection").show();
		$("#lotteryWalletTab").addClass('accountTabActive');
	} else if(div == 3){
		$(".accountTab").hide();
		$("#myDetailsTab,#lotteryWalletTab,#notificationTab").removeClass('accountTabActive');
		$("#lotteryOrderSection").show();
		$("#lotteryOrderTab").addClass('accountTabActive');
	} else if(div == 4){
		$(".accountTab").hide();
		$("#myDetailsTab,#lotteryWalletTab,#lotteryOrderTab").removeClass('accountTabActive');
		$("#notificationSection").show();
		$("#notificationTab").addClass('accountTabActive');
	}
}

/*-------------------- FUNCTION TO REMEMBER FORM DETAILS, SO BY CLICKING CANCEL, ORIGINAL FORM DETAILS COME BACK ------------------------*/
$(function(){
	$('#acctDetailsForm').find(':input').each(function(i, elem) {
		 var input = $(elem);
		 input.data('initialState', input.val());
	});
	
	$('#paymentMethodForm').find(':input').each(function(i, elem) {
		 var input = $(elem);
		 input.data('initialState', input.val());
	});
	
	$('#acctSecurityQuestionsForm').find(':input').each(function(i, elem) {
		var input = $(elem);
		input.data('initialState', input.val());
	});
});

/*------------------------------------ ACCOUNT: PROFILE ------------------------------------*/
$('#acctDetailsForm').each(function() {  // attach to all form elements on page
	$(this).validate({       // initialize plugin on each form
		rules: {
			acctDetailsTitle : { required: true },
			acctDetailsFirstName : { required: true },
			acctDetailsLastName : { required: true },
			acctDetailsPhone : { required: true },
			acctDetailsAddress : { required: true },
			city : { required: true },
			acctDetailsCountry : { required: true }
		  },
		messages: {
			acctDetailsTitle : "",
			acctDetailsFirstName : "",
			acctDetailsLastName : "",
			acctDetailsPhone : "",
			acctDetailsAddress : "",
			city : "",
			state : "",
			acctDetailsCountry : ""
		}
	});
});
/* // user is not allowed to change countries
$("#acctDetailsCountry").on("change",function(){
	var country = $("#acctDetailsCountry").val();
	setPaymentAddress("","acctDetailsCity",country,"acctDetailsCountry");
});
*/
/*
$("#customerProfileDropDown").on("click",function(){
	var country = $("#acctDetailsCountry").val();
	var city = $("#acctDetailsCurrentCity").val();
	setPaymentAddress(city,"acctDetailsCity",country,"acctDetailsCountry");
});
*/
$("#acctDetailsForm :input").keyup(function() {
	$("#updateAcctDetailsButton").removeClass("accountSubmitButtonInactive");
	$("#acctDetailsSubmitCancel").show();
});

$(document).on('change','.acctDetailsSelect',function(){
	$("#updateAcctDetailsButton").removeClass("accountSubmitButtonInactive");
	$("#acctDetailsSubmitCancel").show();
});

$("#acctDetailsSubmitCancel").on("click", function(){
	$("#updateAcctDetailsButton").addClass("accountSubmitButtonInactive");
	$("#acctDetailsForm input,#acctDetailsForm select").removeClass("error");
	$("#acctDetailsSubmitCancel").hide();
	restoreAcctDetails();
});	

function restoreAcctDetails() {
	$('#acctDetailsForm').find(':input').each(function(i, elem) {
		 var input = $(elem);
		 input.val(input.data('initialState'));
	});
	//var country = $("#acctDetailsCountry").val();
	//var city = $("#acctDetailsCurrentCity").val();
	//setPaymentAddress(city,"acctDetailsCity",country,"acctDetailsCountry");
}

$("#acctDetailsForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	$(".loader").show();
	$("#acctDetailsForm").css('pointer-events','none');
	var acctDetailsEmail = $("input[name='acctDetailsEmail']").val();
	var acctDetailsPhone = $("input[name='acctDetailsPhone']").val();
	var acctDetailsAddress = $("input[name='acctDetailsAddress']").val();
	var acctDetailsPostCode = $("input[name='acctDetailsPostCode']").val();
	var acctDetailsCity = $("select[name='city']").val();
	var acctDetailsState = $("select[name='state']").val();
	$.post("resources/php_functions/update-account-details.php",{
		acctDetailsEmail: acctDetailsEmail,
		acctDetailsPhone: acctDetailsPhone,
		acctDetailsAddress: acctDetailsAddress,
		acctDetailsPostCode: acctDetailsPostCode,
		acctDetailsCity: acctDetailsCity,
		acctDetailsState: acctDetailsState
	},
	function(data,status){
		console.log(data);
		$("#acctDetailsForm").css('pointer-events','initial');
		$(".loader").hide();
		if(data == "success"){
			sessionStorage.reloadAfterProfileUpdate = true;
			location.reload(true);
			//$("#updateAcctDetailsButton").addClass("accountSubmitButtonInactive");
			//$("#acctDetailsSubmitCancel,.accountUpdateFail").hide();
			//$('.accountSuccessMessage').html("Update Successful");
			//$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		} else if(data == "successPromoOffer"){
			sessionStorage.reloadAfterProfileUpdateForPromo = true;
			location.reload(true);
		} else {
			if(data == "failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Update Failed<br><br>"+data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
	});
});
	
/*--------------------------------- ACCOUNT: NOTIFICATIONS ---------------------------------*/
$("#acctNotificationForm :input").change(function() {
  $("#updateAcctNotificationButton").removeClass("accountSubmitButtonInactive");
  $("#acctNotificationCancel").show();
});

$("#acctNotificationCancel").on("click", function(){
	$("#updateAcctNotificationButton").addClass("accountSubmitButtonInactive");
	$("#acctNotificationCancel").hide();
	//$("#smsNotifiction").attr('checked', false);
	//$("#allNotifications").attr('checked', false);
	//$("#acctDetailsNotifications").attr('checked', false);
	
});

$("#acctNotificationForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	$(".loader").show();
	var smsNotifiction = false;
	var acctNotifications = $("input[name='acctNotifications']:checked").val();
	if ($('#smsNotifiction').is(':checked')) {
		smsNotifiction = true;
	}
	
	$("#acctNotificationForm").css('pointer-events','none');
	$.post("resources/php_functions/account-notifications.php",{
		smsNotifiction: smsNotifiction,
		acctNotifications: acctNotifications
	},
	function(data,status){
		console.log(data);
		$("#acctNotificationForm").css('pointer-events','initial');
		$(".loader").hide();
		if(data == "success"){
			$("#updateAcctDetailsButton").addClass("accountSubmitButtonInactive");
			$("#acctDetailsSubmitCancel,.accountUpdateFail").hide();
			$('.accountSuccessMessage').html("Update Successful");
			$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		} else {
			if(data == "failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Update Failed<br><br>"+data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/* hid 07072021, delete once tested
		if(status == "success"){
			if(data == "success"){
				$("#updateAcctNotificationButton").addClass("accountSubmitButtonInactive");
				$("#acctNotificationCancel,.accountUpdateFailCopy").hide();
				$("#acctNotificationPopup,.accountUpdateSuccess,#overlay").show();
			} else {
				$(".accountUpdateSuccess").hide();
				$("#acctNotificationPopup,.accountUpdateFailCopy,#overlay").show();
				//restore();
			}
		}
		*/
	});
});

/*-------------------------------- ACCOUNT: PASSWORD CHANGE --------------------------------*/
$(function() {
	$('#accountChangePasswordForm').validate({       // initialize plugin on each form
		rules: {
			oldPassword : { required: true },
			newPassword : { required: true, changePasswordCheck: true, checkUsernameNotPassword: true  }
		  },
		messages: {
			oldPassword : "",
			newPassword: {
                required: "",
				changePasswordCheck: "",
				checkUsernameNotPassword: "Password cannot be your email"
            }
		}
	});
	$.validator.addMethod("changePasswordCheck", function(value,element) {
		return /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/.test(value) // consists of only these
	});
	
	$.validator.addMethod("checkUsernameNotPassword", function(value,element) {
		var username = $("input[name=changePasswordEmail]").val().trim().toLowerCase();
		var password = $("#newPassword").val().trim().toLowerCase();
		if(username == password) return false;
		return true;
	});
	
	$("#newPassword").keyup(function(){
		var registerPasswordCheck = $("input[name=newPassword]").val();
		if(registerPasswordCheck.match(/^[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/)){
			$("#changePasswordLength").css("color","#59C203");
		} else {
			$("#changePasswordLength").css("color","#DE5353");
		}
		if(registerPasswordCheck.match(/^(?=.*\d)[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
			$("#changePasswordDigit").css("color","#59C203");
		} else {
			$("#changePasswordDigit").css("color","#DE5353");
		}
		if(registerPasswordCheck.match(/^(?=.*[a-z])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
			$("#changePasswordLower").css("color","#59C203");
		} else {
			$("#changePasswordLower").css("color","#DE5353");
		}
		if(registerPasswordCheck.match(/^(?=.*[A-Z])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
			$("#changePasswordUpper").css("color","#59C203");
		} else {
			$("#changePasswordUpper").css("color","#DE5353");
		}
		if(registerPasswordCheck.match(/^(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
			$("#changePasswordSpecial").css("color","#59C203");
		} else {
			$("#changePasswordSpecial").css("color","#DE5353");
		}
		
		if(registerPasswordCheck.match(/^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/)){
			$("#changePasswordValidation").hide();
		} else {
			$("#changePasswordValidation").show();
		}
	});
	
	$("#accountChangePasswordForm").submit(function(e){
		resetSessionPost(); // reset the session timeout. this function found in index.js
		e.preventDefault();
        var $form = $(this);
        if(! $form.valid()) return false
		$("#accountChangePasswordForm").css('pointer-events','none');
		$(".loader").show();
		var oldPassword = $("input[name='oldPassword']").val();
		var newPassword = $("input[name='newPassword']").val();
		var changePasswordEmail = $("input[name='changePasswordEmail']").val();
		$.post("resources/php_functions/change-password.php",{
			oldPassword: oldPassword,
			newPassword: newPassword,
			changePasswordEmail: changePasswordEmail
		},
		function(data,status){
			$("#accountChangePasswordForm").css('pointer-events','initial');
			$(".loader").hide();
			if(data == "success"){
				$("#updateAcctDetailsButton").addClass("accountSubmitButtonInactive");
				$("#acctDetailsSubmitCancel,.accountUpdateFail").hide();
				$('.accountSuccessMessage').html("Update Successful");
				$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
			} else {
				if(data == "failed"){
					message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
				} else {
					message = "Update Failed<br><br>"+data;
				}
				$(".accountUpdateSuccess").hide();
				$('.accountFailedMessage').html(message);
				$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
			}
			/* // hid 07072021. delete once tested
			if(status == "success"){
				if(data == "success"){
					$("#accountChangePasswordButton").html("Update")
					$("#accountChangePasswordButton").addClass("accountSubmitButtonInactive");
					$("#changePasswordCancel,.accountUpdateFailCopy").hide();
					$("#accountPasswordUpdatedPopup,.accountUpdateSuccess,#overlay").show();
					$("input[name='oldPassword'],input[name='newPassword']").val("");
				} else {
					$(".accountUpdateSuccess").hide();
					$("#accountPasswordUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
					$("#updateAcctDetailsButton").html("Update")
					//restoreAcctChangePassword();
				}
			}
			*/
		});
	});

	$("#accountChangePasswordForm :input").keyup(function() {
		$("#accountChangePasswordButton").removeClass("accountSubmitButtonInactive");
		$("#changePasswordCancel").show();
	});

	$("#changePasswordCancel").on("click", function(){
		$("#accountChangePasswordButton").addClass("accountSubmitButtonInactive");
		$("#accountChangePasswordForm input").removeClass("error");
		$("#changePasswordValidation").show();
		$("#changePasswordValidation span").css("color","#4E4E4E");
		$("#changePasswordCancel").hide();
		$("input[name='oldPassword'],input[name='newPassword']").val("");
	});	
});

function showChangePassword() {
	var x = document.getElementById("newPassword");
	var y = document.getElementById("changePasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
}

/*-------------------- ACCOUNT: SECURITY QUESTION AND ANSWER CHANGE ------------------------*/
$('#acctSecurityQuestionsForm').validate({       // initialize plugin on each form
	rules: {
		securityQuestion : { required: true },
		securityAnswer : { required: true }
	},
	messages: {
		securityQuestion : "",
		securityAnswer : ""
	}
});

$("#acctSecurityQuestionsForm :input").keyup(function() {
	$("#accountSecurityQuestionsButton").removeClass("accountSubmitButtonInactive");
	$("#securityQuestionsCancel").show();
});

$(document).on('change','.securityQuestionSelect',function(){
	$("#accountSecurityQuestionsButton").removeClass("accountSubmitButtonInactive");
	$("#securityQuestionsCancel").show();
});

$("#securityQuestionsCancel").on("click", function(){
	$("#accountSecurityQuestionsButton").addClass("accountSubmitButtonInactive");
	$("#acctSecurityQuestionsForm input,#acctSecurityQuestionsForm select").removeClass("error");
	$("#securityQuestionsCancel").hide();
	restoreSecurityQuestions();
});	

function restoreSecurityQuestions() {
	$('#acctSecurityQuestionsForm').find(':input').each(function(i, elem) {
		 var input = $(elem);
		 input.val(input.data('initialState'));
	});
}

$("#acctSecurityQuestionsForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	$("#acctSecurityQuestionsForm").css('pointer-events','none');
	$(".loader").show();
	var securityQuestion = $("select[name='securityQuestion']").val();
	var securityAnswer = $("input[name='securityAnswer']").val();
	$.post("resources/php_functions/account-security-question.php",{
		securityQuestion: securityQuestion,
		securityAnswer: securityAnswer
	},
	function(data,status){
		$("#acctSecurityQuestionsForm").css('pointer-events','initial');
		$(".loader").hide();
		if(data == "success"){
			$("#updateAcctDetailsButton").addClass("accountSubmitButtonInactive");
			$("#acctDetailsSubmitCancel,.accountUpdateFail").hide();
			$('.accountSuccessMessage').html("Update Successful");
			$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		} else {
			if(data == "failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Update Failed<br><br>"+data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(status == "success"){
			if(data == "success"){
				$("#accountSecurityQuestionsButton").html("Update")
				$("#accountSecurityQuestionsButton").addClass("accountSubmitButtonInactive");
				$("#securityQuestionsCancel,.accountUpdateFailCopy").hide();
				$("#accountSecurityQuestionPopup,.accountUpdateSuccess,#overlay").show();
				$("input[name='securityAnswer']").val("");
			} else {
				$(".accountUpdateSuccess").hide();
				$("#accountSecurityQuestionPopup,.accountUpdateFailCopy,#overlay").show();
				$("#updateAcctDetailsButton").html("Update")
			}
		}
		*/
	});
});

/*----------------------------- ACCOUNT: SET BET AND DEPOSIT LIMITS ------------------------*/
if(window.location.href.indexOf("status=set-limits") > -1) {
	cleanURL();
	goToLimitsSection();
}

$("#linkToSetLimits").on("click",function(){
	goToLimitsSection();
});

function goToLimitsSection(){
	$("#lotteryWalletSection,#lotteryOrderSection,#notificationSection").hide();
	$("#lotteryOrderTab,#notificationTab,#lotteryWalletTab").removeClass('accountTabActive');
	$("#myDetailsSection").show();
	$("#setLimitsDropdown").addClass("active");
	$([document.documentElement, document.body]).animate({
		scrollTop: $("#setLimitsDropdown").offset().top
	}, 1500);
}

$("#acctSetLimitsForm :input").keyup(function() {
	$("#updateAcctLimitsButton").removeClass("accountSubmitButtonInactive");
	$("#acctSetLimitsCancel").show();
});

accountSetBetLimitAmount = $("#acctSetBetLimit").val();
accountSetBetLimitDuration = $("select[name=setBetLimitDuration]").find(":selected").val();
accountSetDepositLimitAmount = $("#acctSetDepositLimit").val();
accountSetDepositLimitDuration = $("select[name=setDepositLimitDuration]").find(":selected").val();

$(function () {
	staticBetLimit = accountSetBetLimitAmount;
	staticBetDuration = accountSetBetLimitDuration;
	staticDepositLimit = accountSetDepositLimitAmount;
	staticDepositDuration = accountSetDepositLimitDuration;
	changeAccountLossLimitCopy();
});

$("#acctSetDepositLimit").change(function () {
	if(!$.isNumeric($(this).val()))
	$(this).val(staticDepositLimit).trigger('change');
	$(this).val(parseFloat($(this).val(), 10).toFixed(2));
});

$("#acctSetBetLimit").keyup(function(){
	var inputBetAmount =  parseFloat($("#acctSetBetLimit").val());
	inputBetAmount = inputBetAmount.toFixed(2);
});

$("#acctSetBetLimit").change(function () {
	if(!$.isNumeric($(this).val()))
	$(this).val(staticBetLimit).trigger('change');
	$(this).val(parseFloat($(this).val(), 10).toFixed(2));
	changeAccountLossLimitCopy();
});

$("select[name=setBetLimitDuration]").on('change',function(){
	var selectBetDurationValue = $("select[name=setBetLimitDuration] option:selected").text();
	changeAccountLossLimitCopy();
});

$(document).on('change','.setBetDepositLimitDuration',function(){
	$("#updateAcctLimitsButton").removeClass("accountSubmitButtonInactive");
	$("#acctSetLimitsCancel").show();
});

$("#acctSetLimitsCancel").on("click", function(){
	$("#acctSetBetLimit").val(staticBetLimit);
	$("select[name=setBetLimitDuration]").val(staticBetDuration);
	$("#acctSetDepositLimit").val(staticDepositLimit);
	$("select[name=setDepositLimitDuration]").val(staticDepositDuration);
	$("#updateAcctLimitsButton").addClass("accountSubmitButtonInactive");
	$("#acctSetLimitsForm input,#acctSetLimitsForm select").removeClass("error");
	$("#acctSetLimitsCancel").hide();
	changeAccountLossLimitCopy()
});	

function changeAccountLossLimitCopy(){
	accountSetBetLimitAmount = $("#acctSetBetLimit").val();
	accountSetBetLimitDuration = $("select[name=setBetLimitDuration]").find(":selected").text();
	if((accountSetBetLimitAmount != 0 && (isNaN(accountSetBetLimitAmount) == false)) && ($("select[name=setBetLimitDuration]").val() != "" )){
		$("#acctSetLimitsLoss").html("Your potential loss limit: "+ accountSetBetLimitAmount +" over " + accountSetBetLimitDuration);
	} else {
		$("#acctSetLimitsLoss").html("Set your play limit to reflect your loss limit.");
	}
}

jQuery.validator.addMethod(
    "validMoney",
    function(value, element) {
        var isValidMoney = /^\d{0,6}(\.\d{0,2})?$/.test(value);
        return this.optional(element) || isValidMoney;
    },
    "Insert "
);

$('#acctSetLimitsForm').each(function() {  // attach to all form elements on page
	$(this).validate({       // initialize plugin on each form
		rules: {
			setBetLimit: {
				validMoney: true,
				min: 1,
				required: true
			},
			setBetLimitDuration : { required: true },
			setDepositLimit: {
				validMoney: true,
				min: 1,
				required: true
			},
			setDepositLimitDuration : { required: true }
		  },
		messages: {
			setBetLimit : "",
			setBetLimitDuration : "",
			setDepositLimit : "",
			setDepositLimitDuration : ""
		}
	});
});

$("#acctSetLimitsForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	$(".loader").show();
	var acctBetAmount = $('input[name="setBetLimit"]').val();
	var acctBetDuration = $('select[name="setBetLimitDuration"]').val();
	var acctDepositAmount = $('input[name="setDepositLimit"]').val();
	var acctDepositDuration = $('select[name="setDepositLimitDuration"]').val();
	var pendingBetLimit = $('input[name="pendingBetLimit"]').val();
	var pendingBetDuration = $('input[name="pendingBetDuration"]').val();
	var pendingBetStartTime = $('input[name="pendingBetStartTime"]').val();
	var pendingDepositLimit = $('input[name="pendingDepositLimit"]').val();
	var pendingDepositDuration = $('input[name="pendingDepositDuration"]').val();
	var pendingDepositStartTime = $('input[name="pendingDepositStartTime"]').val();
	$.post("resources/php_functions/account-set-limits.php",{
		acctBetAmount : acctBetAmount,
		acctBetDuration : acctBetDuration,
		acctDepositAmount : acctDepositAmount,
		acctDepositDuration : acctDepositDuration,
		pendingBetLimit : pendingBetLimit,
		pendingBetDuration : pendingBetDuration,
		pendingBetStartTime : pendingBetStartTime,
		pendingDepositLimit : pendingDepositLimit,
		pendingDepositDuration : pendingDepositDuration,
		pendingDepositStartTime : pendingDepositStartTime
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			sessionStorage.reloadAfterLimitsUpdate = true;
			location.reload(true);
		} else if(data == "failed"){
			message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		} else if(data == "failed cancel pending"){
			sessionStorage.reloadFailedCancelPendingLimits = true;
			sessionStorage.reloadFailedCancelPendingLimitsMessage = "Update Successful<br><br><span class='accountFailedMessage'>But we were unable to cancel your Pending Limits. Please try again, or contact customer service</span>";
			location.reload(true);
		} else {
			message = "Update Failed<br><br>"+data;
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		
		/* // changed 07072021, trying to dispaly api error message and reading from one popup on account page. delete once tested
		if(data == "success"){
			//$("#updateAcctLimitsButton").addClass("accountSubmitButtonInactive");
			//$("#acctSetLimitsCancel,.accountUpdateFailCopy").hide();
			//$("#acctSetLimitsPopup,.accountUpdateSuccess,#overlay").show();
			sessionStorage.reloadAfterLimitsUpdate = true;
			location.reload(true);
		} else {
			$("#acctSetLimitsPopup,.accountUpdateFailCopy,#overlay").show();
		}
		*/
	});
});

//$(".cancelPendingLimits").on("click",function(e){
function cancelPendingLimits(limitAmount,transactionTypeCode,durationInDays,startTime){
	$(".loader").show();
	$.post("resources/php_functions/account-cancel-pending-limits.php",{
		limitAmount : limitAmount,
		transactionTypeCode : transactionTypeCode,
		durationInDays : durationInDays,
		startTime : startTime
	},
	function(data,status){
		$(".loader").hide();
		if(data == "success"){
			sessionStorage.reloadAfterLimitsUpdate = true;
			location.reload(true);
		} else {
			if(data == "failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Update Failed<br><br>"+data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/* // changed 07072021, trying to dispaly api error message and reading from one popup on account page. delete once tested
		if(data == true){
			sessionStorage.reloadAfterLimitsUpdate = true;
			location.reload(true);
		} else {
			$(".loader").hide();
			$("#acctSetLimitsPopup,.accountUpdateFailCopy,#overlay").show();
		}
		*/
	});
}

/*--------------------------------- ACCOUNT: BET LIMIT -------------------------------------*/
/*------------------------------ ACCOUNT: DEPOSIT LIMIT ------------------------------------*/
$('#showDepositLimitInfo').on('click', function () {
	var thisDepositLimitInfoWindow = $(this).closest('div').parent().find('.depositLimitInfoWindow');
	thisDepositLimitInfoWindow.show();
});
/*------------------ ACCOUNT: TIME OUT, SELF EXCLUSION, CLOSE ACCOUNT  ---------------------*/
/* ACCOUNT SUSPEND SECTION */
$('#acctExclusionTimeOutForm').validate({       // initialize plugin on each form
	messages: {
		accountClosePassword : "",
		accountSelfExcludePassword : "",
		accountTimeOutPassword : ""
	}
});
	
$("#accountTimeOut").click(function() {
	restoreAcctSuspendSection();
	$("#accountClose").attr('checked', false);
	$("#accountTimeOutTime").removeClass("acctExludeInactiveSelect");
});

$("#accountSelfExclude").click(function() {
	restoreAcctSuspendSection();
	$("#accountClose").attr('checked', false);
	$("#accountSelfExcludeTime").removeClass("acctExludeInactiveSelect");
});

$("#acctSuspendSection select").change(function() {
  $("#updateAcctExclusionButton").removeClass("accountSubmitButtonInactive");
  $("#acctExclusionCancel").show();
});

$("#acctExclusionCancel").on("click", function(){
	$("#accountSelfExclude").prop('checked', false);
	$("#accountTimeOut").prop('checked', false);
	restoreAcctSuspendSection();
});	

function restoreAcctSuspendSection() {
	$("#acctSuspendSection select").val("");
    $("#accountTimeOutTime").addClass("acctExludeInactiveSelect");
	$("#accountSelfExcludeTime").addClass("acctExludeInactiveSelect");
	$("#updateAcctExclusionButton").addClass("accountSubmitButtonInactive");
	$("#acctExclusionCancel").hide();
	$("#updateAcctCloseButton").addClass("accountSubmitButtonInactive");
	$("#acctCloseCancel").hide();
}

/* ACCOUNT CLOSE SECTION */
$("html").on("click", "#accountClose", function() {// show cancel and update button once something in the form has changed
  restoreAcctSuspendSection();
	$("#accountSelfExclude").prop('checked', false);
	$("#accountTimeOut").prop('checked', false);
	$("#updateAcctCloseButton").removeClass("accountSubmitButtonInactive");
	$("#acctCloseCancel").show();
});

$("html").on("click", "#acctCloseCancel", function() {
	$("#updateAcctCloseButton").addClass("accountSubmitButtonInactive");
	$("#acctCloseCancel").hide();
	$("#accountClose").prop('checked', false);
});

/* SHOW ACCOUNT SUSPENDED POPUPS */
$("#updateAcctExclusionButton").click(function(){
	$('#acctSuspendSection select').removeClass('error');
	var accountSuspendRadio = $('input[name=accountSuspend]:checked', '#acctSuspendSection').val(); 
	if(accountSuspendRadio == "Timeout"){
		if(!$('#accountTimeOutTime').val() == "")  {
			$("#accountTimeOutPopup,#overlay").show();
		} else {
			$('#accountTimeOutTime').addClass('error');
		}
	} else if(accountSuspendRadio == "Self-Exclusion"){
		if( !$('#accountSelfExcludeTime').val() == "")  {
			$("#accountSelfExcludePopup,#overlay").show();
		} else {
			$('#accountSelfExcludeTime').addClass('error');
		}
	}
	return false;
});

$("#accountTimeOutPassword").keyup(function(){
	$("#finalAcctTimeOutButton").removeClass("accountSubmitButtonInactive");
});

$("#accountSelfExcludePassword").keyup(function(){
	$("#finalAcctSelfExcludeButton").removeClass("accountSubmitButtonInactive");
});

$("#accountTimeOutPasswordImage").click(function(){
	var x = document.getElementById("accountTimeOutPassword");
	var y = document.getElementById("accountTimeOutPasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
});

$("#accountSelfExcludePasswordImage").click(function(){
	var x = document.getElementById("accountSelfExcludePassword");
	var y = document.getElementById("accountSelfExcludePasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
});

/* SHOW ACCOUNT CLOSE POPUPS */
$("html").on("click", "#updateAcctCloseButton", function() {
	$("#accountClosePopup,#overlay").show();
	return false;
});

$("html").on("keyup", "#accountClosePassword", function() {
	$("#finalAcctCloseButton").removeClass("accountSubmitButtonInactive");
});

$("#accountClosePasswordImage").click(function(){
	var x = document.getElementById("accountClosePassword");
	var y = document.getElementById("accountClosePasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
});

$("#acctExclusionTimeOutForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	$("#acctExclusionTimeOutForm").css('pointer-events','none');
	$("#accountClosePopup,#accountSelfExcludePopup,#accountTimeOutPopup,#overlay").hide();
	$(".loader").show();
	var acctExclusionOption = $("input[name='accountSuspend']:checked").val();
	var acctTimeOutTime = $("select[name='accountTimeOutTime']").val();
	var acctSelfExcludeTime = $("select[name='accountSelfExcludeTime']").val();
	var accountTimeOutReason = $("textarea[name='accountTimeOutReason']").val();
	var accountSelfExcludeReason = $("textarea[name='accountSelfExcludeReason']").val();
	var accountCloseReason = $("textarea[name='accountCloseReason']").val();
	$.post("resources/php_functions/account-suspension.php",{
		acctExclusionOption: acctExclusionOption,
		acctTimeOutTime: acctTimeOutTime,
		acctSelfExcludeTime: acctSelfExcludeTime,
		accountTimeOutReason: accountTimeOutReason,
		accountSelfExcludeReason: accountSelfExcludeReason,
		accountCloseReason: accountCloseReason
	},
	function(data,status){
		$("#acctExclusionTimeOutForm").css('pointer-events','initial');
		$(".loader").hide();
		console.log(data);
		if(status == "success"){
			if(data == "acctClosedSuccess"){
				$("#closedAcctSuccessPopup,#overlay").show();
				setTimeout(function(){ 
					document.location = "/logout";
				}, 3000);
			} else if(data == "status failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
				$(".accountUpdateSuccess").hide();
				$('.accountFailedMessage').html(message);
				$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
			} else if(data == "timer fail"){
				//message = "Update Failed<br><br>Your account was successfully disabled but we were unable to set a timer. Please contact customer service";
				//$(".accountUpdateSuccess").hide();
				//$('.accountFailedMessage').html(message);
				//$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
				window.scrollTo(0,0);
				sessionStorage.reloadAfterAcctStatusTimerFail = true;
				location.reload(true);
			} else if(data == "success"){
				window.scrollTo(0,0);
				location.reload(true);
			} else {
				//$(".accountUpdateSuccess").hide();
				//$('.accountFailedMessage').html(data);
				//$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
				sessionStorage.reloadAfterAcctStatusFail = true;
				sessionStorage.reloadAfterAcctStatusFailMessage = data;
				location.reload(true);
			}
		}
		/*
		if(status == "success"){
			if(data == "acctClosedSuccess"){
				$("#closedAcctSuccessPopup,#overlay").show();
				setTimeout(function(){ 
					document.location = "/logout";
				}, 3000);
			} else if(data == "fail"){
				$("#updateAccountStatusFailedPopup,#overlay").show();
				setTimeout(function(){
					//$("#updateAccountStatusFailedPopup,#overlay").hide();
					window.scrollTo(0,0);
					location.reload(true);
				}, 2000);
			} else {
				window.scrollTo(0,0);
				location.reload(true);
			}
		}
		*/
	});
});

function addMonths(date, months) {
    var d = date.getDate();
    date.setMonth(date.getMonth() + +months);
    if (date.getDate() != d) {
      date.setDate(0);
    }
    return date;
}

function addDays(date, day) {
    var d = date.getDate();
    date.setDate(date.getDate() + day);
    return date;
}

function AddYears(date,years){
	date.setFullYear(date.getFullYear() + years);
	return date;
}

function startCountdown(isAccountTimeOut,isAccountSelfExcluded,selfExcludeTime){
	if(isAccountTimeOut != "" || isAccountSelfExcluded != ""){
		$("#acctSuspendSection").css('pointer-events','none');
		if(isAccountTimeOut != ""){
			if(selfExcludeTime != ""){
				setTime = selfExcludeTime;
			}
			var x = setInterval(function() {
				accountTimeOutCounter = getAccountExcludeCountdown(setTime);
				$(".timeOutCounter").html(accountTimeOutCounter);
			}, 1000);
		} else if(isAccountSelfExcluded != ""){
			if(selfExcludeTime != ""){
				setTime = selfExcludeTime;
			}
			var x = setInterval(function() {
				accountSelfExcludeCounter = getAccountExcludeCountdown(setTime);
				$(".selfExcludeCounter").html(accountSelfExcludeCounter);
			}, 1000);
		}
	}
}

function getAccountExcludeCountdown(date){
	var countDownDate = new Date(date).getTime();
	var now = new Date().getTime();
	var distance = countDownDate - now;
	var days = Math.floor(distance / (1000 * 60 * 60 * 24));
	var hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
	var minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
	var seconds = Math.floor((distance % (1000 * 60)) / 1000);
	if (distance < 0) {
		clearInterval();
		return "To be announced";
	} else {
		return days + " Day(s) " + hours + ":" + (minutes < 10 ? '0' : '') + minutes + ":" + (seconds < 10 ? '0' : '') + seconds;
	}
}

/*------------------------------------------ ACCOUNT: WALLET SECTION ----------------------------------------------------------*/
/*------------------------------------------ ACCOUNT: WALLET SECTION: WITHDRAWAL ----------------------------------------------*/

$("#searchWithdrawalReset").click(function(){
	$("label[for='acctWithdrawAmount']").hide();
	$("#acctWithdrawAmount").val("");
	$("#acctWithdrawAmount").removeClass("error");
});

$("#accountWithdrawal .useReplacePaymentMethod").click(function(){
	$("#paymentMethodDropdown").addClass("active");
	$([document.documentElement, document.body]).animate({
        scrollTop: $("#paymentMethodDropdown").offset().top
    }, 1500);
});

$("#acctWithdrawAmount").change(function () {
	if(!$.isNumeric($(this).val()))
	$(this).val('0').trigger('change');
	$(this).val(parseFloat($(this).val(), 10).toFixed(2));
});

minWithdrawalAmount = 10;
maxWithdrawalAmount = $('input[name="accountWithdrawAmountAvaiableNoCurrency"]').val();
if(maxWithdrawalAmount != null){
	maxWithdrawalAmount = parseFloat(maxWithdrawalAmount.replace(/,/g, ''), 10); // remove comma and convert string to float
} else {
	maxWithdrawalAmount = 0;
}
withdrawalErrorMsg = "Please enter a value between " + parseFloat(minWithdrawalAmount, 10).toFixed(2) + " and " + maxWithdrawalAmount.toFixed(2);
if(maxWithdrawalAmount < minWithdrawalAmount){
	withdrawalErrorMsg = "The minimum account balance required for withdrawal requests is " + parseFloat(minWithdrawalAmount, 10).toFixed(2);
}

$('#accountWithdrawForm').each(function() {  // attach to all form elements on page
	$(this).validate({       // initialize plugin on each form
		rules: {
			acctWithdrawAmount: {
			  required: true,
			  range: [minWithdrawalAmount, maxWithdrawalAmount]
			}
		  },
		messages: {
			acctWithdrawAmount: withdrawalErrorMsg
		}
	});
});

$("#accountWithdrawForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	$(".loader").show();
	var acctWithdrawAmount = $('input[name="acctWithdrawAmount"]').val();
	var acctWithdrawalCCPosition = $('input[name="acctWithdrawalCCPosition"]').val();
	$.post("resources/php_functions/account-withdrawal.php",{
		withdrawlFormSubmitted: true,
		acctWithdrawAmount : acctWithdrawAmount,
		acctWithdrawalCCPosition : acctWithdrawalCCPosition
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			$("#accountWithdrawal").load(location.href + " #accountWithdrawal",function(){});
			$(".accountUpdateFail").hide();
			$('.accountSuccessMessage').html("Withdrawal Successful");
			$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		} else {
			if(data == "error"){
				message = "Withdrawal Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Withdrawal Failed<br><br>"+data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(data == "error"){
			$("#orderSearchFailedPopup").show();
		} else {
			$("#accountWithdrawal").load(location.href + " #accountWithdrawal",function(){});
		}
		*/
	});
});

//$("#loadMoreTransactions").on("click", function(){
$(document).off('click','#loadMoreWithdrawals');
$(document).on('click','#loadMoreWithdrawals',function(){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreWithdrawals").css("pointer-events","none");
	$.post("resources/php_functions/account-withdrawal.php",{
		loadMoreWithdrawals: true
	},
	function(data,status){
		console.log(data);
		if(status == "success"){
			$("#accountWithdrawTable").load(location.href + " #accountWithdrawTable",function(){
				$(".loader").hide();
				$("#loadMoreWithdrawals").css("pointer-events","auto");
			});
		}
	});
});

/*-------------------------------------------- NEW NEW NEW --------------------------------------------*/
//$("#accountWithdrawForm .custom-select-wrapper").on('click',function(){
$(document).off('click','#accountWithdrawForm .custom-select-wrapper-withdraw');
$(document).on('click','#accountWithdrawForm .custom-select-wrapper-withdraw',function(){
	this.querySelector('.custom-select-withdraw').classList.toggle('open'); // open menu to show all cards
	currentCardClass = $(".custom-select-withdraw__trigger span span").attr('class'); // get the card that is currently shown
	$(".custom-options-withdraw .custom-option-withdraw").each(function(){ // loop through all card options
		getallCards = $(this).find('span').attr('class'); // get class values for all card options
		//if((currentCardClass == getallCards) && (getallCards !== undefined)){ // if this card class is the same for the card that is currently shown: ||| HID THIS, IF CUSTOMER ONLY HAS ONE CARD, IT ACTS WEIRD
		//	$(this).hide(); // hide it
		//} else {
		//	$(this).show(); // else show it
		//}
	});
});

$("#accountWithdrawForm .custom-option-withdraw").on('click',function(){
	selectedContent = $(this).html();
	$('.custom-select-withdraw__trigger span').html(selectedContent);
	getValue = $(this).attr("data-value");
	$('input[name="acctWithdrawalCCPosition"]').val(getValue);
});
/* // THIS (document.querySelectorAll) ISN'T WORKING IN IE SO REPLACED WITH THE ABOVE.
for (const option of document.querySelectorAll("#accountWithdrawForm .custom-option-withdraw")) {
    option.addEventListener('click', function() {
        if (!this.classList.contains('selected')) {
			selectedContent = $(this).html();
			$('.custom-select-withdraw__trigger span').html(selectedContent);
			getValue = $(this).attr("data-value");
			$('input[name="acctWithdrawalCCPosition"]').val(getValue);
        }
    })
}
*/
/*-------------------------------------------- NEW NEW NEW --------------------------------------------*/
/*------------------------------------------ ACCOUNT: WALLET SECTION: TRANSACTION HISTORY ----------------------------------------------*/
var start = moment().subtract(29, 'days');
var end = moment();

function cb(start, end) {
	$('input[name="dateRangerTransactionHistory"]').val(start.format('MMM D, YYYY') + ' - ' + end.format('MMM D, YYYY'));
}

$('input[name="dateRangerTransactionHistory"]').daterangepicker({
	startDate: start,
	endDate: end,
	ranges: {
		'Today': [moment(), moment()],
		'Yesterday': [moment().subtract(1, 'days'), moment().subtract(1, 'days')],
		'Last 7 Days': [moment().subtract(6, 'days'), moment()],
		'Last 30 Days': [moment().subtract(29, 'days'), moment()],
		'This Month': [moment().startOf('month'), moment().endOf('month')],
		'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
	},
	locale: {
      format: 'YYYY-MM-DD'
    }
}, cb);

$("#accountTransactionHistoryReset").click(function(){
	$('input[name="dateRangerTransactionHistory"]').val(start.format('YYYY-MM-DD') + ' - ' + end.format('YYYY-MM-DD'));
	$("#transactionHistoryType,#transactionHistoryStatus").val("");
});

//$(".transactionHistoryTableBody").off('click');
//$(".transactionHistoryTableBody").on('click', function () {
$(document).off('click','.transactionHistoryTableBody');
$(document).on('click','.transactionHistoryTableBody',function(){
	var jQarrow = $(this).find(".glyphicon");
	var isShowBorder = $(this).find(".transactionHistoryTableBodyCell");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
		isShowBorder.css("border-bottom","1px solid #549CC9");
	} else {
		$(this).addClass('active');
		jQarrow.addClass("open");
		isShowBorder.css("border","none");
	}
});

//$("#loadMoreTransactions").on("click", function(){
$(document).off('click','#loadMoreTransactions');
$(document).on('click','#loadMoreTransactions',function(){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreTransactions").css("pointer-events","none");
	$.post("resources/php_functions/account-transaction-history.php",{
		loadMoreTransactions: true
	},
	function(data,status){
		if(status == "success"){
			$("#transactionHistorySection").load(location.href + " #transactionHistorySection",function(){
				$(".loader").hide();
				$("#loadMoreTransactions").css("pointer-events","auto");
			});
		}
	});
});

$("#accountTransactionForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	$(".loader").show();
	var accountTransactionDateRange = $("input[name='dateRangerTransactionHistory']").val();
	var transactionHistoryType = $("select[name='transactionHistoryType']").val();
	var transactionHistoryStatus = $("select[name='transactionHistoryStatus']").val();
	$.post("resources/php_functions/account-transaction-history.php",{
		transactionFormSubmitted: true,
		accountTransactionDateRange:accountTransactionDateRange,
		transactionHistoryType:transactionHistoryType,
		transactionHistoryStatus:transactionHistoryStatus
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			$("#transactionHistorySection").load(location.href + " #transactionHistorySection", function(){});
		} else {
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(data == "error" || status != "success"){
			$(".loader").hide();
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
		} else {
			$("#transactionHistorySection").load(location.href + " #transactionHistorySection", function(){
				$(".loader").hide();
			});
		}
		
		if(status == "success"){
			if(data == "error"){
				$(".loader").hide();
				$("#transactionSearchFailedPopup").show();
			} else {
				$("#transactionHistorySection").load(location.href + " #transactionHistorySection", function(){
					$(".loader").hide();
				});
			}
		} else {
			$(".loader").hide();
			$("#transactionSearchFailedPopup").show();
		}
		*/
	});
});

/*------------------------------------------ ACCOUNT: WALLET SECTION: WINNINGS----------------------------------------------*/
function goToWinningsSection(){
	$("#myDetailsSection,#lotteryOrderSection,#notificationSection").hide();
	$("#myDetailsTab,#lotteryOrderTab,#notificationTab").removeClass('accountTabActive');
	$("#lotteryWalletSection").show();
	$("#lotteryWalletTab").addClass('accountTabActive');	
	$("#winningsTableDropdown").addClass("active");
	$([document.documentElement, document.body]).animate({
		scrollTop: $("#winningsTableDropdown").offset().top
	}, 1500);
}

var start = moment().subtract(29, 'days');
var end = moment();

function cb(start, end) {
	$('input[name="dateRangerWinnings"]').val(start.format('MMM D, YYYY') + ' - ' + end.format('MMM D, YYYY'));
}

$('input[name="dateRangerWinnings"]').daterangepicker({
	startDate: start,
	endDate: end,
	ranges: {
		'Today': [moment(), moment()],
		'Yesterday': [moment().subtract(1, 'days'), moment().subtract(1, 'days')],
		'Last 7 Days': [moment().subtract(6, 'days'), moment()],
		'Last 30 Days': [moment().subtract(29, 'days'), moment()],
		'This Month': [moment().startOf('month'), moment().endOf('month')],
		'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
	},
	locale: {
      format: 'YYYY-MM-DD'
    }
}, cb);

$("#searchWinningsReset").click(function(){
	$('input[name="dateRangerWinnings"]').val(start.format('YYYY-MM-DD') + ' - ' + end.format('YYYY-MM-DD'));
});

//$("#loadMoreWinnings").on("click", function(){
$(document).off('click','#loadMoreWinnings');
$(document).on('click','#loadMoreWinnings',function(){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreWinnings").css("pointer-events","none");
	$.post("resources/php_functions/account-winnings.php",{
		loadMoreWinnings: true
	},
	function(data,status){
		if(status == "success"){
			$("#accountWinningsTable").load(location.href + " #accountWinningsTable",function(){
				$(".loader").hide();
				$("#loadMoreWinnings").css("pointer-events","auto");
			});
		}
	});
});

$("#accountWinningsForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	$(".loader").show();
	var accountWinningsDateRange = $("input[name='dateRangerWinnings']").val();
	$.post("resources/php_functions/account-winnings.php",{
		accountWinningsFormSubmitted: true,
		accountWinningsDateRange:accountWinningsDateRange
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			$("#accountWinningsTable").load(location.href + " #accountWinningsTable", function(){});
		} else {
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(data == "error" || status != "success"){
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
		} else {
			$("#accountWinningsTable").load(location.href + " #accountWinningsTable", function(){
			});
		}
		
		if(status == "success"){
			if(data == "error"){
				$("#winningsSearchFailedPopup").show();
			} else {
				$("#accountWinningsTable").load(location.href + " #accountWinningsTable",function(){
				});
			}
		} else {
			$("#winningsSearchFailedPopup").show();
		}
		*/
	});
});

/*------------------------------------------ ACCOUNT: WALLET SECTION: PAYMENT METHOD ----------------------------------------------*/
$(".accountPaymentMethodList").delegate(":radio","click",function(e){
	if($("#cancelUpdatePaymentMethod").is(":visible")){ // customer was in the middle of editing, prevent radio from being clicked and show customer a popup first
		e.preventDefault();	
	}
});

$(".accountPaymentMethodList").on('click',function(){
	if(!$("#cancelUpdatePaymentMethod").is(":visible")){
		resetPaymentMethodImages();
		$('.accountPaymentMethodList').removeClass("paymentMethodActive");
		$(this).addClass("paymentMethodActive");
		
		if($(this).hasClass('newPaymentMethod')){
			$(".removedPaymentMethod").hide();
			$("#updatePaymentMethodButton").html("Save");
		}
		
		if(!$(this).hasClass('newPaymentMethod')){
			$(".removedPaymentMethod").show();
			imageSrc = $(this).find('.paymentLogo').attr('src');
			if(imageSrc.includes("Mastercard")){
				defaultImg = "Mastercard_Logo.svg";
				//replaceImg = "Mastercard_Logo_White.svg";
				replaceImg = "Mastercard_Logo.svg";
			} else if(imageSrc.includes("Visa")){
				defaultImg = "Visa_Logo.svg";
				//replaceImg = "Visa_Logo_White.svg";
				replaceImg = "Visa_Logo.svg";
			}
			
			var src = $(this).find('.paymentLogo').attr('src').replace(defaultImg,replaceImg);
			$(this).find('.paymentLogo').attr('src', src);
			$("#updatePaymentMethodButton").html("Update");
		}
	}
});

function resetPaymentMethodImages(){
	$('.paymentLogo').each(function(){
		if($(this).attr('src').includes("Mastercard")){
			defaultImg = "Mastercard_Logo.svg";
			//replaceImg = "Mastercard_Logo_White.svg";
			replaceImg = "Mastercard_Logo.svg";
		} else if($(this).attr('src').includes("Visa")){
			defaultImg = "Visa_Logo.svg";
			//replaceImg = "Visa_Logo_White.svg";
			replaceImg = "Visa_Logo.svg";
		}
			defaultSrc = $(this).attr('src').replace(replaceImg,defaultImg);
		if($(this).attr('src').includes("White")){
		} else {
			defaultSrc = $(this).attr('src').replace(defaultImg,defaultImg);
		}
		$(this).attr('src', defaultSrc);
	});  
}

function paymentMethodAddCard(){
	if($("#cancelUpdatePaymentMethod").is(":visible")){
		$("#paymentMethodPendingChanges,#overlay").show();
		$("#paymentMethodPendingChangesContinue").attr("onClick", "paymentMethodAddCard()");
		$("#clickedPaymentMethodId").val("paymentMethodAddCard");
	} else {
		$('#acctPaymentMethod select, #acctPaymentMethod input').val("");
		$('input[name="paymentMethodsCardNumber"]').css("width","170px");
		$('.paymentMethodCVVField,.paymentMethodsAddressCheckbox').show();
		$('input[name="paymentMethodsAddressCheckbox"]').prop('checked', true);
		$('.paymentMethodBillingAddress').hide();
		//$('input[name="paymentMethodsCardNumber"],input[name="paymentMethodsCardholderName"]').removeClass('nonUpdatableField');
		$('input[name="paymentMethodsCardNumber"],input[name="paymentMethodsCardholderName"]').removeClass('disabledState');
	}
}

function populatePaymentMethodForm(cardHolderName,cardNumber,expMM,expYY,billingCountry,billingAddress,billingCity,billingZip,cardId,fullCardNumber,id){
	if($("#cancelUpdatePaymentMethod").is(":visible")){
		$("#paymentMethodPendingChanges,#overlay").show();
		$("#clickedPaymentMethodId").val(id);
		$("#paymentMethodPendingChangesContinue").attr("onClick", "populatePaymentMethodForm('"+cardHolderName+"','"+cardNumber+"','"+expMM+"','"+expYY+"','"+billingCountry+"','"+billingAddress+"','"+billingCity+"','"+billingZip+"','"+cardId+"','"+fullCardNumber+"')");
	} else {
		$('input[name="paymentMethodsCardholderName"]').val(cardHolderName);
		$('input[name="paymentMethodsCardNumber"]').val("**** **** " + cardNumber);
		$('input[name="paymentMethodsCardNumber"],input[name="paymentMethodsCardholderName"]').addClass('disabledState');
		$('select[name="paymentMethodsCardExpMM"]').val(expMM);
		$('select[name="paymentMethodsCardExpYY"]').val(expYY);
		//$('select[name="paymentMethodsAddressCountry"]').val(billingCountry);
		$('input[name="paymentMethodsAddress"]').val(billingAddress);
		//$('select[name="paymentMethodsAddressCity"]').val(billingCity);
		$('input[name="paymentMethodsAddressZip"]').val(billingZip);
		$('input[name="paymentMethodCCId"], input[name="removePaymentMethodCCId"]').val(cardId);
		$('input[name="paymentMethodMaskCCNumber"]').val(fullCardNumber);
		
		$('input[name="paymentMethodsCardNumber"]').css("width","305px");
		$('.paymentMethodCVVField,.paymentMethodsAddressCheckbox').hide();
		$('.paymentMethodBillingAddress').show();
		//$('input[name="paymentMethodsCardNumber"],input[name="paymentMethodsCardholderName"]').addClass('nonUpdatableField');
		setPaymentAddress(billingCity,"paymentMethodsAddressCity",billingCountry,"paymentMethodsAddressCountry");
	}
}

$('input[name="paymentMethodsAddressCheckbox"]').click(function(){
	if($(this).is(":checked")){
		$(".paymentMethodBillingAddress").hide();
		$(".paymentMethodBillingAddress").hide();
	} else if($(this). is(":not(:checked)")){
		$(".paymentMethodBillingAddress").show();
	}
});

$("html").on("keyup", "#paymentMethodForm", function() {
	$("#updatePaymentMethodButton").removeClass("accountSubmitButtonInactive");
	$("#cancelUpdatePaymentMethod").show();
});

$("#paymentMethodForm select").on("change",function(){
	$("#updatePaymentMethodButton").removeClass("accountSubmitButtonInactive");
	$("#cancelUpdatePaymentMethod").show();
});

$("#cancelUpdatePaymentMethod").on('click',function(){
	$('.newPaymentMethod input:radio').click();
	$("#cancelUpdatePaymentMethod").hide();
	$("#updatePaymentMethodButton").addClass("accountSubmitButtonInactive");
	restorePaymentDetails();
});

function restorePaymentDetails() {
	$('#paymentMethodForm').find(':input').each(function(i, elem) {
		 var input = $(elem);
		 input.val(input.data('initialState'));
	});
}

$("#paymentMethodForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	var $form = $(this);
	if(! $form.valid()) return false
	let name = $('input[name="paymentMethodsCardholderName"]').val();
	let number = $('input[name="paymentMethodsCardNumber"]').val().replace(new RegExp('-', 'g'),"");
	if(name === number){
		$('input[name="paymentMethodsCardholderName"]').addClass('error');
		alert('Cardholder Name and Card Number cannot be the same');
		return false;
	}
	$(".loader").show();
	var paymentMethodsCardholderName = $('input[name="paymentMethodsCardholderName"]').val();
	var paymentMethodsCardNumber = $('input[name="paymentMethodsCardNumber"]').val();
	var paymentMethodsCVV = $('input[name="paymentMethodsCVV"]').val();
	var paymentMethodsCardExpMM = $('select[name="paymentMethodsCardExpMM"]').val();
	var paymentMethodsCardExpYY = $('select[name="paymentMethodsCardExpYY"]').val();
	var paymentMethodsAddressCheckbox = $('input[name="paymentMethodsAddressCheckbox"]');
	if($(paymentMethodsAddressCheckbox).prop("checked") == true){
		paymentMethodsAddressCheckbox = true;
	} else {
		paymentMethodsAddressCheckbox = false;
	}
	var paymentMethodsAddressCountry = $('select[name="paymentMethodsAddressCountry"]').val();
	var paymentMethodsAddress = $('input[name="paymentMethodsAddress"]').val();
	var paymentMethodsAddressCity = $('select[name="paymentMethodsAddressCity"]').val();
	var paymentMethodsAddressZip = $('input[name="paymentMethodsAddressZip"]').val();
	var paymentMethodCCId = $('input[name="paymentMethodCCId"]').val();
	var paymentMethodMaskCCNumber = $('input[name="paymentMethodMaskCCNumber"]').val();
	$.post("resources/php_functions/account-payment-methods.php",{
		paymentMethodsCardholderName : paymentMethodsCardholderName,
		paymentMethodsCardNumber : paymentMethodsCardNumber,
		paymentMethodsCVV : paymentMethodsCVV,
		paymentMethodsCardExpMM : paymentMethodsCardExpMM,
		paymentMethodsCardExpYY : paymentMethodsCardExpYY,
		paymentMethodsAddressCheckbox : paymentMethodsAddressCheckbox,
		paymentMethodsAddressCountry : paymentMethodsAddressCountry,
		paymentMethodsAddress : paymentMethodsAddress,
		paymentMethodsAddressCity : paymentMethodsAddressCity,
		paymentMethodsAddressZip : paymentMethodsAddressZip,
		paymentMethodCCId : paymentMethodCCId,
		paymentMethodMaskCCNumber : paymentMethodMaskCCNumber
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			sessionStorage.reloadAfterPageLoadPaymentMethodUpdate = true;
			location.reload(true);
		} else {
			if(data == "failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Update Failed<br><br>" + data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
			//$(".accountUpdateSuccess").hide();
			//$("#paymentMethodUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
		}
	});
});

$(".removedPaymentMethod").on('click',function(){
	$("#removePaymentMethodPopup,#overlay").show();
});

$("#removePaymentMethodForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	$("#removePaymentMethodPopup,#overlay").hide();
	$(".loader").show();
	var removePaymentMethodCCId = $('input[name="removePaymentMethodCCId"]').val();
	$.post("resources/php_functions/account-payment-methods.php",{
		removePaymentMethodCCId: removePaymentMethodCCId
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			sessionStorage.reloadAfterPageLoadPaymentMethodUpdate = true;
			location.reload(true);
		} else {
			if(data == "failed"){
				message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
			} else {
				message = "Update Failed<br><br>" + data;
			}
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html(message);
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
			//$(".accountUpdateSuccess").hide();
			//$("#paymentMethodUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
		}
	});
});

$(function(){
	if(sessionStorage.reloadAfterLimitsUpdate == "true"){
		$("#setLimitsDropdown").addClass("active");
		$(".accountUpdateFail").hide();
		$('.accountSuccessMessage').html("Update Successful");
		$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		sessionStorage.reloadAfterLimitsUpdate = false;
	}
	if(sessionStorage.reloadFailedCancelPendingLimits == "true"){
		$("#setLimitsDropdown").addClass("active");
		message = "Update Successful<br><br><span class='accountFailedMessage'>But we were unable to cancel your Pending Limits. Please try again, or contact customer service</span>";
		if(sessionStorage.reloadFailedCancelPendingLimitsMessage != 'undefined'){
			message = sessionStorage.reloadFailedCancelPendingLimitsMessage;
		}
		$(".accountUpdateFail").hide();
		$('.accountSuccessMessage').html(message);
		$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		sessionStorage.reloadFailedCancelPendingLimits = false;
		sessionStorage.reloadFailedCancelPendingLimitsMessage = "";
	}
	if(sessionStorage.reloadAfterPageLoadPaymentMethodUpdate == "true"){
		$("#paymentMethodDropdown").click();
		$(".accountUpdateFail").hide();
		$('.accountSuccessMessage').html("Update Successful");
		$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		sessionStorage.reloadAfterPageLoadPaymentMethodUpdate = false;
	}
	if(sessionStorage.reloadAfterAcctStatusFail == "true"){
		message = "Update Failed<br><br>An error has occurred. Please try again or contact customer service";
		if(sessionStorage.reloadAfterAcctStatusFailMessage != 'undefined'){
			message = "Update Failed<br><br>"+sessionStorage.reloadAfterAcctStatusFailMessage;
		}
		$(".accountUpdateSuccess").hide();
		$('.accountFailedMessage').html(message);
		$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		sessionStorage.reloadAfterAcctStatusFail = false;
		sessionStorage.reloadAfterAcctStatusFailMessage = "";
	}
	if(sessionStorage.reloadAfterAcctStatusTimerFail == "true"){
		$(".accountUpdateSuccess").hide();
		$('.accountFailedMessage').html("Update Failed<br><br>Your account was successfully disabled but we were unable to set a timer. Please contact customer service");
		$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		sessionStorage.reloadAfterAcctStatusTimerFail = false;
	}
	if(sessionStorage.reloadAfterProfileUpdate == "true"){
		$("#customerProfileDropDown").click();
		$('.accountSuccessMessage').html("Update Successful");
		$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		sessionStorage.reloadAfterProfileUpdate = false;
	}
	if(sessionStorage.reloadAfterProfileUpdateForPromo == "true"){
		$("#customerProfileDropDown").click();
		$('.accountSuccessMessage').html("Update Successful<br><br>You will receive a Free Play");
		$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		sessionStorage.reloadAfterProfileUpdateForPromo = false;
	}
});

$("#paymentMethodsAddressCountry").on("change",function(){
	billingCountry = $(this).val();
	setPaymentAddress("","paymentMethodsAddressCity",billingCountry,"paymentMethodsAddressCountry");
});

$("#paymentMethodPendingChangesCancel").on("click",function(){
	$("#paymentMethodPendingChanges,#overlay").hide();
});

$("#paymentMethodPendingChangesContinue").on("click",function(){
	$("#cancelUpdatePaymentMethod").hide();
	$("#updatePaymentMethodButton").addClass("accountSubmitButtonInactive");
	$("#paymentMethodPendingChanges,#overlay").hide();
	var clickedPaymentMethodId = $("#clickedPaymentMethodId").val();
	if(clickedPaymentMethodId == "paymentMethodAddCard"){
		$(".newPaymentMethod input:radio").prop("checked", true);
		$(".newPaymentMethod").click();
	} else {
		$("#"+clickedPaymentMethodId+".accountPaymentMethodList input:radio").prop("checked", true);
		$("#"+clickedPaymentMethodId+".accountPaymentMethodList").click();
	}
});

/*------------------------------------------ ACCOUNT: ORDERS SECTION: ORDER HISTORY ----------------------------------------------*/
var start = moment().subtract(1, 'month');
var end = moment();

function cb(start, end) {
	$('input[name="dateRangerOrderHistory"]').val(start.format('MMM D, YYYY') + ' - ' + end.format('MMM D, YYYY'));
}

$('input[name="dateRangerOrderHistory"]').daterangepicker({
	startDate: start,
	endDate: end,
	ranges: {
		'Today': [moment(), moment()],
		'Yesterday': [moment().subtract(1, 'days'), moment().subtract(1, 'days')],
		'Last 7 Days': [moment().subtract(6, 'days'), moment()],
		'Last 30 Days': [moment().subtract(29, 'days'), moment()],
		'This Month': [moment().startOf('month'), moment().endOf('month')],
		'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
	},
	locale: {
      format: 'YYYY-MM-DD'
    }
}, cb);

$("#accountOrderHistoryReset").click(function(){
	$("#orderHistoryNo,#orderHistoryType,#orderHistoryOpen,#orderHistoryStatus").val("");
	$('input[name="dateRangerOrderHistory"]').val(start.format('YYYY-MM-DD') + ' - ' + end.format('YYYY-MM-DD'));
});

//$(".orderHistoryTableBody").off('click');
//$(".orderHistoryTableBody").on('click', function () {
$(document).off('click','.orderHistoryTableBodyOne');
$(document).on('click','.orderHistoryTableBodyOne',function(){
	var jQarrow = $(this).find(".glyphicon");
	var isShowBorder = $(this).find(".orderHistoryTableBodyCell");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
		isShowBorder.css("border-bottom","1px solid #549CC9");
	} else {
		isShowBorder.css("border","none");
		$(this).addClass('active');
		jQarrow.addClass("open");
	}
});

//$(".orderHistoryTableTwo .orderHistoryTableBody").off('click');
//$(".orderHistoryTableTwo .orderHistoryTableBody").on('click', function () {
$(document).off('click','.orderHistoryTableBodyTwo');
$(document).on('click','.orderHistoryTableBodyTwo',function(){
	var jQarrow = $(this).find(".glyphicon");
	var isShowBorder = $(this).find(".orderHistoryTableBodyCell");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
		isShowBorder.css("border-bottom","1px solid #549CC9");
	} else {
		$(this).addClass('active');
		jQarrow.addClass("open");
		isShowBorder.css("border","none");
	}
});

$('.showFulDateInfo').on('click', function () {
	//$(".fulDateInfoWindow").show();
	var thisFulDateInfoWindow = $(this).closest('div').next('div').next('div').next('div').next('div');
	thisFulDateInfoWindow.show();
});

$('.showTotalWinsInfo').on('click', function () {
	var thisTotalWinsInfoWindow = $(this).closest('div').parent().find('.totalWinsInfoWindow');
	thisTotalWinsInfoWindow.show();
});

$(document).off('click','.showTotalWinsInfo');
$(document).on('click','.showTotalWinsInfo',function(){
	var thisTotalWinsInfoWindow = $(this).closest('div').parent().find('.totalWinsInfoWindow');
	thisTotalWinsInfoWindow.show();
});

$('.showWinAmountInfo').on('click', function () {
	var thisWinAmountInfoWindow = $(this).closest('div').parent().find('.winAmountInfoWindow');
	thisWinAmountInfoWindow.show();
});

$(document).off('click','.showWinAmountInfo');
$(document).on('click','.showWinAmountInfo',function(){
	var thisWinAmountInfoWindow = $(this).closest('div').parent().find('.winAmountInfoWindow');
	thisWinAmountInfoWindow.show();
});

$("#accountOrderHistoryForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	$(".loader").show();
	var orderHistoryDateSearch = $('input[name="dateRangerOrderHistory"]').val();
	var orderId = $('input[name="orderHistoryNo"]').val();
	var orderStatus = $('select[name="orderHistoryStatus"]').val();
	var orderSettled = $('select[name="orderHistoryOpen"]').val();
	var orderType = $('select[name="orderHistoryType"]').val();
	$.post("resources/php_functions/account-order-history.php",{
		orderFormSubmitted: true,
		orderId: orderId,
		orderStatus: orderStatus,
		orderHistoryDateSearch: orderHistoryDateSearch,
		orderSettled: orderSettled,
		orderType: orderType
	},
	function(data,status){
		console.log(data);
		$(".loader").hide();
		if(data == "success"){
			$("#orderHistoryTable").load(location.href + " #orderHistoryTable",function(){});
		} else {
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(data == "error"){
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
		} else {
			$("#orderHistoryTable").load(location.href + " #orderHistoryTable",function(){});
		}

		if(data == "error"){
			$("#orderSearchFailedPopup").show();
		} else {
			$("#orderHistoryTable").load(location.href + " #orderHistoryTable",function(){
			});
		}
		*/
	});
});

//$("#loadMoreOrderHistory").on("click", function(){
$(document).off('click','#loadMoreOrderHistory');
$(document).on('click','#loadMoreOrderHistory',function(){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreOrderHistory").css("pointer-events","none");
	$.post("resources/php_functions/account-order-history.php",{
		loadMoreOrderHistory: true
	},
	function(data,status){
		if(status == "success"){
			$("#orderHistoryTable").load(location.href + " #orderHistoryTable", function(){
				$(".loader").hide();
				$("#loadMoreOrderHistory").css("pointer-events","auto");
			});
		}
	});
});

function loadMoreOrderHistoryTickets(totalTickets,sessionCount,positionOne,positionTwo){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreOrderHistoryTickets").css("pointer-events","none");
	$.post("resources/php_functions/account-order-history.php",{
		loadMoreOrderHistoryTickets: true,
		totalTickets: totalTickets,
		sessionCount: sessionCount,
		positionOne: positionOne,
		positionTwo: positionTwo
	},
	function(data,status){
		if(status == "success"){
			$("#testing"+positionOne+"_"+positionTwo).load(location.href + " #testing"+positionOne+"_"+positionTwo, function(){
				if(data == "noMore"){
					$("#loadMoreOrderHistoryTickets").animate({'color': 'transparent'}, '500');
				}
				$(".loader").hide();
				$("#loadMoreOrderHistoryTickets").css("pointer-events","auto");
			});
		}
	});
}

$(".betAgain").on("click",function(e){
	e.stopPropagation();
	var boards = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainBoards').html();
	boards = getOrderHistryBetAgainBoards(boards);
	var orderDays = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainDays').html();
	var orderWeeks = getOrderHistoryBetAgainWeeks(orderDays);
	orderDays = getOrderHistryBetAgainDays(orderDays);
	var productId = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainProductId').html();
	var productCode = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainProductCode').html();
	var productName = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainProductName').html();
	var productUnitPrice = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainUnitPrice').html();
	var productLotteryId = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainLotteryId').html();
	var isSubscription = $(e.target).closest('.orderHistoryTableBody').next('.orderHistoryTableTwo').find('.orderHistoryBetAgainPlayType').html();
	isSubscription = getProductType(isSubscription)

	$("#orderHistoryBetAgainTicketNumbers").val(boards);
	$("#orderHistoryBetAgainProductId").val(productId);
	$("#orderHistoryBetAgainProductCode").val(productCode);
	$("#orderHistoryBetAgainItemName").val(productName);
	$("#orderHistoryBetAgainLotteryId").val(productLotteryId);
	$("#orderHistoryBetAgainUnitPrice").val(productUnitPrice);
	$("#orderHistoryBetAgainLottoDays").val(orderDays);
	$("#orderHistoryBetAgainSinglePlayWeeks").val(orderWeeks);
	$("#orderHistoryBetAgainSubscriptionCheckbox").val(isSubscription);
	$("#betAgainForm").submit();
});

function getProductType(isSubscription){
	if(isSubscription == "Sub"){ return true; }
	else if(isSubscription == "Single"){ return false; }
}

function weeksBetween(d1, d2) {
    return Math.ceil(((d2 - d1) / (7 * 24 * 60 * 60 * 1000)) + 0.001);
}

function getOrderHistoryBetAgainWeeks(weeks){
	weeks = JSON.parse(weeks);
	return weeksBetween(new Date(weeks[0]),new Date(weeks[weeks.length-1]));
}

function getOrderHistryBetAgainDays(days){
	days = JSON.parse(days);
	betAgainDays = new Array();
	for(var i=0;i<days.length;i++){
		orderDay = new Date(days[i]).toLocaleDateString('en', {weekday:'long'});
		if(betAgainDays.includes(orderDay) == false){
			betAgainDays.push(orderDay);
		}
	}
	return JSON.stringify(betAgainDays);
}

function getOrderHistryBetAgainBoards(boards){
	boards = JSON.parse(boards);
	betAgainLines = new Array();
	lines = new Array();
	for(var i=0;i<boards.length;i++){
		if(lines.includes(boards[i]) == false){
			lines.push(boards[i]);
			splitBoards = boards[i].split(';');
			replaceBoardNumbers = splitBoards[0].split(' ');
			boardNumbers = new Array();
			for(var j=0;j<replaceBoardNumbers.length;j++){
				boardNumbers.push(parseInt(replaceBoardNumbers[j]));
			}
			boardBonusNumbers = "";
			if(splitBoards[1]){
				replaceBoardBonusNumbers = splitBoards[1].split(' ');
				boardBonusNumbers = new Array();
				for(var k=0;k<replaceBoardBonusNumbers.length;k++){
					boardBonusNumbers.push(parseInt(replaceBoardBonusNumbers[k]));
				}
			}
			betAgainLines.push({index:i+1,Numbers:boardNumbers,BonusNumbers:boardBonusNumbers});
		}
	}
	return JSON.stringify(betAgainLines);
}

/*------------------------------------------ ACCOUNT: ORDER SECTION: BET HISTORY -------------------------------------------------*/
var start = moment().subtract(29, 'days');
var end = moment();

function cb(start, end) {
	$('input[name="dateRangerBetHistory"]').val(start.format('MMM D, YYYY') + ' - ' + end.format('MMM D, YYYY'));
}

$('input[name="dateRangerBetHistory"]').daterangepicker({
	startDate: start,
	endDate: end,
	ranges: {
		'Today': [moment(), moment()],
		'Yesterday': [moment().subtract(1, 'days'), moment().subtract(1, 'days')],
		'Last 7 Days': [moment().subtract(6, 'days'), moment()],
		'Last 30 Days': [moment().subtract(29, 'days'), moment()],
		'This Month': [moment().startOf('month'), moment().endOf('month')],
		'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
	},
	locale: {
      format: 'YYYY-MM-DD'
    }
}, cb);

$("#accountBetHistoryReset").click(function(){
	$("#betHistoryLottery, #betHistoryOrderNumber, #betHistoryStatus").val("");
	$('input[name="dateRangerBetHistory"]').val(start.format('YYYY-MM-DD') + ' - ' + end.format('YYYY-MM-DD'));
	$("#betHistoryIsSettled,#betHistoryIsSubscription").val("2");
	$("#betHistoryIsWinsOnly").val("no");
});

$(document).off('click','.betHistoryTableBody');
$(document).on('click','.betHistoryTableBody',function(){
	var jQarrow = $(this).find(".glyphicon");
	var isShowBorder = $(this).find(".betHistoryTableBodyCell");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
		isShowBorder.css("border-bottom","1px solid #549CC9");
		$(".betHistoryUpperTable").last().find(".betHistoryTableBodyCell").css("border-bottom","1px solid #549CC9");
	} else {
		$(this).addClass('active');
		jQarrow.addClass("open");
		isShowBorder.css("border","none");
		$(".betHistoryTableTwo").last().css("border-bottom","1px solid #549CC9");
	}
});

$("#accountBetForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	$(".loader").show();
	var betHistoryDateSearch = $('input[name="dateRangerBetHistory"]').val();
	var betHistoryOrderNumber = $('input[name="betHistoryOrderNumber"]').val();
	var betHistoryLotteryName = $('select[name="betHistoryLottery"]').val();
	//var betHistoryType = $('select[name="betHistoryType"]').val();
	var betHistoryStatus = $('select[name="betHistoryStatus"]').val();
	var betHistoryIsSettled = $('select[name="betHistoryIsSettled"]').val();
	var betHistoryWinsOnly = $('select[name="betHistoryIsWinsOnly"]').val();
	var betHistoryIsSubscription = $('select[name="betHistoryIsSubscription"]').val();
	//var betHistory = $('select[name=""]').val();
	$.post("resources/php_functions/account-bet-history.php",{
		accountBetFormSubmitted: true,
		betHistoryDateSearch: betHistoryDateSearch,
		betHistoryOrderNumber: betHistoryOrderNumber,
		//betHistoryType: betHistoryType,
		betHistoryStatus: betHistoryStatus,
		betHistoryIsSettled: betHistoryIsSettled,
		betHistoryWinsOnly: betHistoryWinsOnly,
		betHistoryIsSubscription: betHistoryIsSubscription,
		betHistoryLotteryName: betHistoryLotteryName
	},
	function(data,status){
		$(".loader").hide();
		console.log(data);
		if(data == "success"){
			$("#betHistoryTable").load(location.href + " #betHistoryTable",function(){});
		} else {
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(data == "error"){
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
			//$("#orderSearchFailedPopup").show();
			//$(".loader").hide();
		} else {
			$("#betHistoryTable").load(location.href + " #betHistoryTable",function(){});
		}
		*/
	});
});

$(document).off('click','#loadMoreBets');
$(document).on('click','#loadMoreBets',function(){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreBets").css("pointer-events","none");
	$.post("resources/php_functions/account-bet-history.php",{
		loadMoreBetHistory: true
	},
	function(data,status){
		if(status == "success"){
			$("#betHistorySection").load(location.href + " #betHistorySection",function(){
				$(".loader").hide();
				$("#loadMoreBets").css("pointer-events","auto");
			});
		}
	});
});

$(".betHistoryUpperTable").last().find(".betHistoryTableBodyCell").css("border-bottom","1px solid #549CC9");

/*------------------------------------------ ACCOUNT: ORDERS SECTION: SUBSCRIPTION HISTORY ----------------------------------------------*/
var start = moment().subtract(29, 'days');
var end = moment();

function cb(start, end) {
	$('input[name="dateRangerSubscriptionHistory"]').val(start.format('MMM D, YYYY') + ' - ' + end.format('MMM D, YYYY'));
}

$('input[name="dateRangerSubscriptionHistory"]').daterangepicker({
	startDate: start,
	endDate: end,
	ranges: {
		'Today': [moment(), moment()],
		'Yesterday': [moment().subtract(1, 'days'), moment().subtract(1, 'days')],
		'Last 7 Days': [moment().subtract(6, 'days'), moment()],
		'Last 30 Days': [moment().subtract(29, 'days'), moment()],
		'This Month': [moment().startOf('month'), moment().endOf('month')],
		'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
	},
	locale: {
      format: 'YYYY-MM-DD'
    }
}, cb);

$("#accountSubscriptionHistoryReset").click(function(){
	$("#orderSubscriptionNo,#subscriptionProductName,#subscriptionStatus").val("");
	$('input[name="dateRangerSubscriptionHistory"]').val(start.format('YYYY-MM-DD') + ' - ' + end.format('YYYY-MM-DD'));
});

//$(".subscriptionHistoryTableBody").off('click');
//$(".subscriptionHistoryTableBody").on('click', function () {
$(document).off('click','.subscriptionHistoryTableBody');
$(document).on('click','.subscriptionHistoryTableBody',function(){
	var jQarrow = $(this).find(".glyphicon");
	var isShowBorder = $(this).find(".subscriptionHistoryTableBodyCell");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
		isShowBorder.css("border-bottom","1px solid #549CC9");
	} else {
		$(this).addClass('active');
		jQarrow.addClass("open");
		isShowBorder.css("border","none");
	}
});

//$('.showSubcripDrawWinInfo').on('click', function () {
$(document).off('click','.showSubcripDrawWinInfo');
$(document).on('click','.showSubcripDrawWinInfo',function(){
	//$(".syndFillStatusInfoWindow").show();
	var thisSubscripDrawWinInfoWindow = $(this).closest('div').next('div');
	thisSubscripDrawWinInfoWindow.show();
});

$("#accountSubscriptionHistoryForm").submit(function(e){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	e.preventDefault();
	$(".loader").show();
	var subscriptionHistoryDateRange = $('input[name="dateRangerSubscriptionHistory"]').val();
	var subscriptionHistoryOrderNumber = $('input[name="orderSubscriptionNo"]').val();
	var subscriptionHistoryProductName = $('select[name="subscriptionProductName"]').val();
	var subscriptionHistoryStatus = $('select[name="subscriptionStatus"]').val();
	$.post("resources/php_functions/account-subscription-history.php",{
		subscriptionHistoryFormSubmitted: true,
		subscriptionHistoryDateRange: subscriptionHistoryDateRange,
		subscriptionHistoryOrderNumber: subscriptionHistoryOrderNumber,
		subscriptionHistoryProductName: subscriptionHistoryProductName,
		subscriptionHistoryStatus: subscriptionHistoryStatus
	},
	function(data,status){
		$(".loader").hide();
		console.log(data);
		if(data == "success"){
			$("#subscriptionHistoryTable").load(location.href + " #subscriptionHistoryTable",function(){});
		} else {
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
		}
		/*
		if(data == "error"){
			$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
			$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
			//$("#orderSearchFailedPopup").show();
			//$(".loader").hide();
		} else {
			$("#subscriptionHistoryTable").load(location.href + " #subscriptionHistoryTable",function(){});
		}
		*/
	});
});

$(document).off('click','#loadMoreSubscriptions');
$(document).on('click','#loadMoreSubscriptions',function(){
	resetSessionPost(); // reset the session timeout. this function found in index.js
	$(".loader").show();
	$("#loadMoreSubscriptions").css("pointer-events","none");
	$.post("resources/php_functions/account-subscription-history.php",{
		loadMoreSubscriptions: true
	},
	function(data,status){
		if(status == "success"){
			$("#subscriptionHistoryTable").load(location.href + " #subscriptionHistoryTable",function(){
				$(".loader").hide();
				$("#loadMoreSubscriptions").css("pointer-events","auto");
			});
		}
	});
});
/*------------------------------------------ ACCOUNT: ORDERS SECTION: TRANSACTION SUMMARY ----------------------------------------------*/
/* // dont think this is being used anymore?? 07072021. delete after testing
$("#accountTransactionSummary li").click(function(){
	clickedSearchItem = $(this).html();
	$("#accountTransactionSummary li").removeClass("acctTransSummaryActive");
	$(this).addClass("acctTransSummaryActive");
});
*/

$(".transactionSummary").click(function(){
	if(!$(".transactionSummary").hasClass("active")){
		$(".loader").show();
		$.post("resources/php_functions/account-transaction-summary.php",{
			loadTransactionSummary: true
		},
		function(data,status){
			$(".loader").hide();
			console.log(data);
			if(data == "success"){
				$(".accountTransactionSummary").load(location.href + " #accountTransactionSummaryWallet div .walletPageContent",function(){}); // 2 summary sections, only load the one div (#accountTransactionSummaryWallet) in both
			} else {
				$(".accountUpdateSuccess").hide();
				$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
				$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
				$(".transactionSummary").removeClass("active");
			}
			/* // replaced this 07072021. delete after testing
			if(data == "error" || status != "success"){
				$('.accountFailedMessage').html('Search Failed<br><br>Please try again or contact customer service');
				$("#accountUpdatedPopup,.accountUpdateFailCopy,#overlay").show();
				$(".transactionSummary").removeClass("active");
			} else {
				$(".accountTransactionSummary").load(location.href + " #accountTransactionSummaryWallet div .walletPageContent",function(){}); // 2 summary sections, only load the one div (#accountTransactionSummaryWallet) in both
			}
			
			if(status == "success"){
				$(".accountTransactionSummary").load(location.href + " #accountTransactionSummaryWallet div .walletPageContent",function(){}); // 2 summary sections, only load the one div (#accountTransactionSummaryWallet) in both
			}
			*/
		});
	}
});